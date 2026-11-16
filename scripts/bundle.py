#!/usr/bin/env python3
"""Optional external plugin preparation. Never builds or changes a Jenkins image/home."""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
CUSTOM = ROOT / 'custom-plugins'
LOCK = ROOT / 'plugins.lock.json'
def target_core():
    """Read the manually selected FROM tag; never change it or install an upgrade."""
    match = re.search(r'^FROM\s+docker\.io/jenkins/jenkins:(\d+\.\d+\.\d+)-lts-jdk25@sha256:[0-9a-f]{64}\s*$',
                      (ROOT / 'Containerfile').read_text(), re.MULTILINE)
    if not match:
        raise ValueError('Use an exact LTS-jdk25 tag and verified digest in Containerfile FROM')
    return match.group(1)


def manifest(path):
    with zipfile.ZipFile(path) as archive:
        raw = archive.read('META-INF/MANIFEST.MF').decode('utf-8')
    unfolded = re.sub(r'\n ', '', raw.replace('\r\n', '\n')).split('\n\n', 1)[0]
    return dict(line.rstrip('\r').split(': ', 1) for line in unfolded.splitlines() if ': ' in line)


def custom_plugins(directory=None):
    directory = directory or CUSTOM
    result = {}
    for path in sorted(directory.iterdir()):
        if path.suffix not in ('.hpi', '.jpi'):
            continue
        if path.is_symlink():
            raise ValueError(f'Symlink is not accepted: {path}')
        data = manifest(path)
        name, version = data.get('Short-Name', ''), data.get('Plugin-Version', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not version or not data.get('Jenkins-Version'):
            raise ValueError(f'Missing/invalid plugin manifest: {path}')
        if name in result:
            raise ValueError(f'Duplicate custom plugin ID: {name}')
        result[name] = (path, data)
    return result


def requests():
    result = {}
    for raw in (ROOT / 'plugins.txt').read_text().splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if not re.fullmatch(r'[A-Za-z0-9_-]+:[A-Za-z0-9_.+-]+', line):
            raise ValueError('Every plugins.txt entry must be ID:exact-version')
        name, version = line.split(':')
        if version in ('latest', 'experimental') or 'SNAPSHOT' in version:
            raise ValueError(f'Non-reproducible version: {line}')
        if name in result:
            raise ValueError(f'Duplicate official plugin ID: {name}')
        result[name] = version
    return result


def manifest_requirements(data):
    result = []
    for ref in data.get('Plugin-Dependencies', '').split(','):
        if not ref.strip():
            continue
        fields = ref.strip().split(';')
        pair = fields[0].split(':', 1)
        if len(pair) != 2 or not re.fullmatch(r'[A-Za-z0-9_-]+', pair[0]) or not pair[1]:
            raise ValueError(f'Invalid plugin dependency: {ref}')
        result.append(dict(name=pair[0], version=pair[1], optional='resolution:=optional' in fields))
    return result


def dependencies(data):
    for dependency in manifest_requirements(data):
        if not dependency['optional']:
            yield [dependency['name'], dependency['version']]


def plugin_info(data):
    return dict(version=data['Plugin-Version'], requiredCore=data['Jenkins-Version'],
                dependencies=manifest_requirements(data))


def validate_graph(plugins, core, war):
    if not plugins:
        return
    checks, edges = [], {}
    for name, data in plugins.items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not data.get('version'):
            raise ValueError(f'Invalid plugin identity: {name}')
        required_core = data.get('requiredCore', '')
        if not re.fullmatch(r'\d+(\.\d+)*', required_core):
            raise ValueError(f'Unknown requiredCore for {name}: {required_core}')
        checks.append((core, required_core, f'{name} requires newer Jenkins {required_core}'))
        edges[name] = []
        for dependency in data.get('dependencies', []):
            dep, minimum = dependency['name'], dependency['version']
            if not re.fullmatch(r'[A-Za-z0-9_-]+', dep) or not minimum:
                raise ValueError(f'Invalid dependency metadata for {name}')
            if dep not in plugins:
                if dependency.get('optional', False):
                    continue
                raise ValueError(f'{name} requires unlocked {dep}:{minimum}: include all required plugins')
            edges[name].append(dep)
            checks.append((plugins[dep]['version'], minimum,
                           f'{name} requires {dep}:{minimum}; selected {plugins[dep]["version"]}'))
    visiting, visited = set(), set()

    def visit(name):
        if name in visiting:
            raise ValueError(f'Cyclic plugin dependency: {name}')
        if name not in visited:
            visiting.add(name)
            for dep in edges[name]:
                visit(dep)
            visiting.remove(name)
            visited.add(name)

    for name in plugins:
        visit(name)
    if not war:
        raise ValueError('Nonempty plugin sets require --war pointing to the exact target Jenkins WAR for version checks')
    if manifest(war).get('Jenkins-Version') != core:
        raise ValueError(f'Version-check WAR must be Jenkins {core}')
    with zipfile.ZipFile(war) as archive, tempfile.TemporaryDirectory() as temporary:
        jars = [name for name in archive.namelist()
                if re.fullmatch(r'WEB-INF/lib/version-number-[^/]+\.jar', name)]
        if len(jars) != 1:
            raise ValueError('Cannot locate Jenkins VersionNumber in the target WAR')
        jar = Path(temporary) / 'version-number.jar'
        jar.write_bytes(archive.read(jars[0]))
        source = Path(temporary) / 'CompareVersions.java'
        source.write_text(
            'import hudson.util.VersionNumber;\n'
            'class CompareVersions {\n'
            '    public static void main(String[] args) {\n'
            '        for (int i = 0; i < args.length; i += 2) {\n'
            '            System.out.println(new VersionNumber(args[i]).compareTo(new VersionNumber(args[i + 1])) >= 0);\n'
            '        }\n'
            '    }\n'
            '}\n')
        java = str(Path(os.environ['JAVA_HOME']) / 'bin/java') if os.environ.get('JAVA_HOME') else 'java'
        command = [java, '--class-path', str(jar), str(source)]
        command.extend(str(value) for actual, minimum, _ in checks for value in (actual, minimum))
        completed = subprocess.run(command, text=True, capture_output=True, timeout=60)
        results = completed.stdout.splitlines()
        if completed.returncode or len(results) != len(checks) or any(value not in ('true', 'false') for value in results):
            raise ValueError(f'Jenkins version validation failed: {completed.stderr[-1000:]}')
        for (_, _, message), result in zip(checks, results):
            if result != 'true':
                raise ValueError(message)


def locked_plugins(lock):
    for name, data in lock['plugins'].items():
        if not re.fullmatch(r'[0-9a-f]{64}', data.get('sha256', '')):
            raise ValueError(f'Invalid SHA-256 lock for {name}')
        if not isinstance(data.get('dependencies'), list):
            raise ValueError(f'Missing dependency metadata for {name}: run resolve and review lock')
    return lock['plugins']


def metadata(path, url):
    if path:
        return json.loads(Path(path).read_text())
    with urlopen(url, timeout=60) as response:
        return json.load(response)


def resolve(args):
    core = target_core()
    catalog = metadata(args.metadata, 'https://updates.jenkins.io/current/update-center.actual.json')
    versions = metadata(args.versions, '') if args.versions else None
    direct = requests()
    custom = custom_plugins()
    if set(direct) & set(custom):
        raise ValueError('A plugin cannot be both official and custom')
    pending = set(direct)
    for _, data in custom.values():
        pending.update(name for name, _ in dependencies(data) if name not in custom)
    selected = {}
    while pending:
        name = pending.pop()
        if name in selected or name in custom:
            continue
        data = catalog['plugins'].get(name)
        if name in direct and (not data or data['version'] != direct[name]):
            data = (versions or {}).get('plugins', {}).get(name, {}).get(direct[name])
        if not data:
            raise ValueError(f'No verified metadata for {name}. For older pins supply --versions plugin-versions.json')
        required_core = data.get('requiredCore', '')
        if not re.fullmatch(r'\d+(\.\d+)*', required_core):
            raise ValueError(f'Unknown requiredCore for {name}: {required_core}')
        digest = base64.b64decode(data['sha256'], validate=True).hex()
        if len(digest) != 64:
            raise ValueError(f'Invalid SHA-256 metadata: {name}')
        selected[name] = dict(version=data['version'], sha256=digest, requiredCore=required_core,
                              dependencies=data.get('dependencies', []),
                              url=data.get('url', f'https://updates.jenkins.io/download/plugins/{name}/{data["version"]}/{name}.hpi'))
        pending.update(dep['name'] for dep in data.get('dependencies', []) if not dep['optional'])
    graph = {name: plugin_info(data) for name, (_, data) in custom.items()}
    validate_graph(dict(selected, **graph), core, getattr(args, 'war', None))
    output = dict(core=core, resolvedAt=datetime.now(timezone.utc).isoformat(),
                  source='https://updates.jenkins.io/current/update-center.actual.json',
                  requested=direct, plugins=dict(sorted(selected.items())))
    LOCK.write_text(json.dumps(output, indent=2) + '\n')
    print(f'Locked {len(selected)} official plugins; review plugins.lock.json before build')


def prepare(_args):
    lock = json.loads(LOCK.read_text())
    if lock['core'] != target_core() or lock['requested'] != requests():
        raise ValueError('plugins.txt/core changed: run resolve and review lock')
    custom = custom_plugins()
    if set(custom) & set(lock['plugins']):
        raise ValueError('Official/custom plugin collision')
    official = locked_plugins(lock)
    for name, version in lock['requested'].items():
        if name not in official or official[name]['version'] != version:
            raise ValueError(f'Requested pin {name}:{version} differs from lock: run resolve')
    graph = {name: plugin_info(data) for name, (_, data) in custom.items()}
    validate_graph(dict(official, **graph), lock['core'], getattr(_args, 'war', None))
    build = ROOT / 'build'
    if build.exists():
        shutil.rmtree(build)
    (build / 'custom').mkdir(parents=True)
    sums, custom_lock = [], {}
    for name, (path, data) in sorted(custom.items()):
        target = build / 'custom' / (name + '.jpi')
        shutil.copyfile(path, target)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        sums.append(f'{digest}  {name}.jpi')
        custom_lock[name] = {'version': data['Plugin-Version'], 'sha256': digest,
                             'requiredCore': data['Jenkins-Version'],
                             'dependencies': data.get('Plugin-Dependencies', '')}
    for name, data in lock['plugins'].items():
        sums.append(f'{data["sha256"]}  {name}.jpi')
    (build / 'plugins.txt').write_text(''.join(f'{name}:{data["version"]}\n' for name, data in lock['plugins'].items()))
    (build / 'jenkins-core-version').write_text(target_core() + '\n')
    (build / 'plugins.sha256').write_text('\n'.join(sorted(sums)) + '\n')
    (build / 'custom-plugins.lock.json').write_text(json.dumps(custom_lock, indent=2) + '\n')
    print(f'Prepared {len(custom)} custom plugins and {len(lock["plugins"])} locked official plugins')
    print('Validate the complete plugin set separately before copying it into the stopped server plugins directory')


def export_plugins(args):
    """External workstation only; produces a bundle for manual, stopped-server deployment."""
    prepare(args)
    lock = json.loads(LOCK.read_text())
    output = ROOT / 'build' / 'plugin-bundle'
    with tempfile.TemporaryDirectory(dir=ROOT / 'build') as temporary:
        staged = Path(temporary) / 'plugins'
        shutil.copytree(ROOT / 'build' / 'custom', staged)
        for name, data in lock['plugins'].items():
            with urlopen(data['url'], timeout=90) as response:
                body = response.read()
            if hashlib.sha256(body).hexdigest() != data['sha256']:
                raise ValueError(f'Checksum mismatch: {name}')
            path = staged / (name + '.jpi')
            path.write_bytes(body)
            info = manifest(path)
            if info.get('Short-Name') != name or info.get('Plugin-Version') != data['version']:
                raise ValueError(f'Plugin manifest differs from lock: {name}')
        actual = {name: plugin_info(data) for name, (_, data) in custom_plugins(staged).items()}
        validate_graph(actual, lock['core'], getattr(args, 'war', None))
        shutil.move(str(staged), output)
    print(f'Exported {len(list(output.glob("*.jpi")))} plugins to {output}; image was not rebuilt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    resolve_parser = sub.add_parser('resolve', help='Explicitly refresh the official dependency lock')
    resolve_parser.add_argument('--metadata', help='Saved update-center.actual.json (offline)')
    resolve_parser.add_argument('--versions', help='Saved official plugin-versions.json for older pins')
    prepare_parser = sub.add_parser('prepare', help='Prepare optional plugin inputs; an empty plugin set is valid')
    export_parser = sub.add_parser('export', help='Externally download locked plugins/dependencies and include local HPI/JPI files')
    for command in (resolve_parser, prepare_parser, export_parser):
        command.add_argument('--war', help='Exact target Jenkins WAR; required for nonempty plugin sets and Jenkins version comparison (Java 11+)')
    args = parser.parse_args()
    try:
        {'resolve': resolve, 'prepare': prepare, 'export': export_plugins}[args.command](args)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        sys.exit(str(error))


if __name__ == '__main__':
    main()
