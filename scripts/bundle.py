#!/usr/bin/env python3
"""Optional external plugin preparation. Never builds or changes a Jenkins image/home."""
import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
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


def dependencies(data):
    for ref in data.get('Plugin-Dependencies', '').split(','):
        if not ref.strip():
            continue
        fields = ref.strip().split(';')
        if 'resolution:=optional' not in fields:
            yield fields[0].split(':', 1)


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
        if tuple(map(int, required_core.split('.'))) > tuple(map(int, core.split('.'))):
            raise ValueError(f'{name}:{data["version"]} requires newer Jenkins {required_core}; choose a compatible pin')
        digest = base64.b64decode(data['sha256'], validate=True).hex()
        if len(digest) != 64:
            raise ValueError(f'Invalid SHA-256 metadata: {name}')
        selected[name] = dict(version=data['version'], sha256=digest, requiredCore=required_core,
                              url=data.get('url', f'https://updates.jenkins.io/download/plugins/{name}/{data["version"]}/{name}.hpi'))
        pending.update(dep['name'] for dep in data.get('dependencies', []) if not dep['optional'])
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
    known = set(custom) | set(lock['plugins'])
    for name, (_, data) in custom.items():
        for dep, _ in dependencies(data):
            if dep not in known:
                raise ValueError(f'{name} requires unlocked {dep}: run resolve with the custom artifacts present')
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
    shutil.copytree(ROOT / 'build' / 'custom', output)
    for name, data in lock['plugins'].items():
        with urlopen(data['url'], timeout=90) as response:
            body = response.read()
        if hashlib.sha256(body).hexdigest() != data['sha256']:
            raise ValueError(f'Checksum mismatch: {name}')
        path = output / (name + '.jpi')
        path.write_bytes(body)
        info = manifest(path)
        if info.get('Short-Name') != name or info.get('Plugin-Version') != data['version']:
            raise ValueError(f'Plugin manifest differs from lock: {name}')
    print(f'Exported {len(list(output.glob("*.jpi")))} plugins to {output}; image was not rebuilt')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    resolve_parser = sub.add_parser('resolve', help='Explicitly refresh the official dependency lock')
    resolve_parser.add_argument('--metadata', help='Saved update-center.actual.json (offline)')
    resolve_parser.add_argument('--versions', help='Saved official plugin-versions.json for older pins')
    sub.add_parser('prepare', help='Prepare optional plugin inputs; an empty plugin set is valid')
    sub.add_parser('export', help='Externally download locked plugins/dependencies and include local HPI/JPI files')
    args = parser.parse_args()
    try:
        {'resolve': resolve, 'prepare': prepare, 'export': export_plugins}[args.command](args)
    except (ValueError, OSError, KeyError, zipfile.BadZipFile) as error:
        sys.exit(str(error))


if __name__ == '__main__':
    main()
