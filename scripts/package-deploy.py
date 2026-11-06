#!/usr/bin/env python3
"""Package a locally built image and clean runtime settings for offline deployment."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUTS = ('Containerfile', '.env.example', 'podman-compose.yml',
          'podman-compose.https.yml', 'deployment/https.properties.example',
          'deployment/README.offline.txt.in')


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def podman(*args):
    return subprocess.run(['podman', *args], check=True, text=True, capture_output=True).stdout


def inspect_image(image):
    data = json.loads(podman('image', 'inspect', image))
    if len(data) != 1:
        raise ValueError('Expected one locally built image')
    return data[0]


def render_env(source, values):
    lines = source.splitlines()
    for key, value in values.items():
        found = False
        for i, line in enumerate(lines):
            if line.startswith(key + '='):
                lines[i] = key + '=' + value
                found = True
        if not found:
            lines.append(key + '=' + value)
    return '\n'.join(lines) + '\n'


def make_package(root, output_dir, image=None, platform='linux/amd64'):
    root = Path(root).resolve()
    output_dir = Path(output_dir).resolve()
    # An allowlist prevents shipping .env, live homes, plugin binaries, or private keys.
    for name in INPUTS:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Missing input or symlink not permitted: {name}')
    match = re.search(r'^FROM\s+\S*[-:]jdk(\d+)\b', (root / 'Containerfile').read_text(), re.MULTILINE)
    if not match:
        raise ValueError('Cannot determine JDK version from Containerfile FROM')
    jdk = match.group(1)
    env_source = (root / '.env.example').read_text()
    if image is None:
        match = re.search(r'^JENKINS_IMAGE=(\S+)\s*$', env_source, re.MULTILINE)
        if not match:
            raise ValueError('No default JENKINS_IMAGE in .env.example')
        image = match.group(1)
    # Require a named tag so podman load can restore exactly the reference in Compose.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]*:[A-Za-z0-9_][A-Za-z0-9_.-]*', image):
        raise ValueError('Use a named local image tag, e.g. localhost/jenkins-25:version-amd64')
    info = inspect_image(image)
    if image not in info.get('RepoTags', []):
        raise ValueError('Use an exact RepoTags reference from podman image inspect')
    actual_platform = info.get('Os', '') + '/' + info.get('Architecture', '')
    if actual_platform != platform:
        raise ValueError(f'Image platform is {actual_platform}; expected {platform}. Build the correct platform first')
    image_env = dict(value.split('=', 1) for value in info.get('Config', {}).get('Env', []) if '=' in value)
    java_version = image_env.get('JAVA_VERSION', '')
    if java_version:
        java_major = re.match(r'(?:jdk-)?(\d+)', java_version)
        if java_major and java_major.group(1) != jdk:
            raise ValueError('Image JAVA_VERSION differs from the JDK selected in Containerfile')
    core = image_env.get('JENKINS_VERSION', 'See image metadata')
    package_name = 'jenkins-podman-jdk' + jdk
    image_archive = f'jenkins-{jdk}-{info["Architecture"]}.oci.tar'
    output_dir.mkdir(parents=True, exist_ok=True)
    final_tar = output_dir / (package_name + '.tar')
    final_checksum = output_dir / (package_name + '.tar.sha256')
    with tempfile.TemporaryDirectory(prefix='.package-', dir=output_dir) as temporary:
        stage = Path(temporary)
        package = stage / package_name
        package.mkdir(mode=0o700)
        for name in ('jenkins_home', 'plugins', 'ssl', 'archives'):
            (package / name).mkdir(mode=0o700)
        for source, name in (('podman-compose.yml', 'podman-compose.yml'),
                             ('podman-compose.https.yml', 'podman-compose-https.yml')):
            shutil.copyfile(root / source, package / name)
        compose_path = package / 'podman-compose.yml'
        compose, replacements = re.subn(
            r'(?m)^(\s*image:\s*)\$\{JENKINS_IMAGE:-[^}]+\}',
            lambda match: match.group(1) + '${JENKINS_IMAGE:-' + image + '}',
            compose_path.read_text(), count=1)
        if replacements != 1:
            raise ValueError('Expected JENKINS_IMAGE fallback in podman-compose.yml')
        compose_path.write_text(compose)
        shutil.copyfile(root / 'deployment/https.properties.example', package / 'ssl/https.properties.example')
        (package / '.env.example').write_text(render_env(env_source, {
            'JENKINS_IMAGE': image,
            'JENKINS_HOME_DIR': './jenkins_home',
            'JENKINS_PLUGINS_DIR': './plugins',
            'JENKINS_SSL_DIR': './ssl',
        }))
        archive = package / 'archives' / image_archive
        print(f'Exporting local image: {image} ({actual_platform})', flush=True)
        podman('save', '--format', 'oci-archive', '--output', str(archive), image)
        if not archive.is_file() or archive.stat().st_size == 0:
            raise ValueError('podman save did not produce an image archive')
        if inspect_image(image)['Id'] != info['Id']:
            raise ValueError('Image tag changed while exporting; retry with a stable tag')
        (package / 'archives' / (image_archive + '.sha256')).write_text(sha256(archive) + '  ' + image_archive + '\n')
        (package / 'IMAGE.txt').write_text(
            f'Image: {image}\nImage ID: {info["Id"]}\nPlatform: {actual_platform}\n'
            f'Jenkins: {core}\nJDK selected in Containerfile: {jdk}\n')
        readme = (root / 'deployment/README.offline.txt.in').read_text()
        values = {'PACKAGE_NAME': package_name, 'IMAGE_REF': image, 'IMAGE_ARCHIVE': image_archive,
                  'PLATFORM': actual_platform, 'IMAGE_ID': info['Id'], 'CORE_VERSION': core, 'JDK_VERSION': jdk,
                  'HOST_ARCH': {'amd64': 'x86_64', 'arm64': 'aarch64'}[info['Architecture']]}
        for key, value in values.items():
            readme = readme.replace('@@' + key + '@@', value)
        if re.search(r'@@[A-Z_]+@@', readme):
            raise ValueError('Unresolved placeholder in offline README')
        (package / 'README.txt').write_text(readme)
        payload = sorted(path for path in package.rglob('*') if path.is_file())
        (package / 'SHA256SUMS').write_text(''.join(
            sha256(path) + '  ' + path.relative_to(package).as_posix() + '\n' for path in payload))
        temporary_tar = stage / final_tar.name
        with tarfile.open(temporary_tar, 'w', format=tarfile.PAX_FORMAT) as archive_file:
            def portable(info):
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mode = 0o700 if info.isdir() else 0o600
                return info
            archive_file.add(package, arcname=package_name, filter=portable)
        temporary_checksum = stage / final_checksum.name
        temporary_checksum.write_text(sha256(temporary_tar) + '  ' + final_tar.name + '\n')
        # Replace generated outputs only after export and all checks have succeeded.
        os.chmod(temporary_tar, 0o600)
        os.chmod(temporary_checksum, 0o600)
        temporary_tar.replace(final_tar)
        temporary_checksum.replace(final_checksum)
    print(f'Created: {final_tar}\nChecksum: {final_checksum}', flush=True)
    return final_tar


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', help='Existing fully qualified local image tag; default: .env.example')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist', help='Default: repository dist/')
    parser.add_argument('--platform', default='linux/amd64', choices=('linux/amd64', 'linux/arm64'))
    args = parser.parse_args()
    try:
        make_package(ROOT, args.output_dir, args.image, args.platform)
    except subprocess.CalledProcessError as error:
        parser.exit(1, 'Podman failed (no image build/pull is performed): ' + (error.stderr or str(error)) + '\n')
    except (OSError, ValueError, KeyError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
