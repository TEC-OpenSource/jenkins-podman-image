#!/usr/bin/env python3
"""Manually reset Jenkins by moving its mounted data to sibling backups."""
import argparse
import datetime
import json
import subprocess
from pathlib import Path

CONTAINER = 'jenkins-25'
DESTINATIONS = ('/var/jenkins_home', '/var/jenkins_home/plugins')


def podman(*args):
    return subprocess.run(['podman', *args], check=True, text=True, capture_output=True).stdout


def mounted_paths(info, root):
    paths = []
    protected = [root.resolve(), Path.home().resolve()]
    system = {Path(name) for name in ('/', '/home', '/Users', '/var', '/usr', '/etc', '/opt', '/tmp', '/data')}
    for destination in DESTINATIONS:
        mounts = [mount for mount in info.get('Mounts', []) if mount.get('Destination') == destination]
        if len(mounts) != 1 or mounts[0].get('Type') != 'bind':
            raise ValueError('Expected one bind mount for ' + destination)
        source = Path(mounts[0]['Source'])
        if not source.is_absolute() or source.is_symlink() or not source.is_dir():
            raise ValueError('Expected a local directory, not a symlink: ' + str(source))
        path = source.resolve()
        if path in system or any(value == path or path in value.parents for value in protected):
            raise ValueError('Refusing to reset a protected directory: ' + str(path))
        paths.append(path)
    home, plugins = paths
    if home == plugins or plugins in home.parents:
        raise ValueError('Plugin directory must not contain the Jenkins home')
    # A nested plugin directory is already included in the home backup.
    return paths, [home] if home in plugins.parents else paths


def reset(root, confirmed=False):
    info = json.loads(podman('inspect', CONTAINER))[0]
    paths, sources = mounted_paths(info, Path(root))
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    moves = [(path, path.with_name(path.name + '.backup-' + stamp)) for path in sources]
    for source, target in moves:
        if target.exists():
            raise ValueError('Backup already exists: ' + str(target))
        print(f'{source} -> {target}', flush=True)
    if not confirmed:
        print('Preview only. Use --reset to stop Jenkins and reset these data directories.')
        return
    podman('stop', '--time', '120', CONTAINER)
    moved = []
    created = []
    try:
        for source, target in moves:
            source.rename(target)
            moved.append((source, target))
        for path in paths:
            # Only empty replacement directories are created; no recursive chmod/chown.
            missing = []
            parent = path
            while not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir(mode=0o700)
                created.append(directory)
        podman('rm', CONTAINER)
    except (OSError, subprocess.CalledProcessError):
        for path in reversed(created):
            path.rmdir()
        for source, target in reversed(moved):
            target.rename(source)
        raise
    print('Reset complete. Backups, env.conf, SSL certificates and Podman secrets are retained.')
    print('Start Jenkins with the same Compose files and --env-file env.conf to run initial setup.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reset', action='store_true', help='Stop/remove the container and back up/reset home and plugins')
    args = parser.parse_args()
    try:
        reset(Path(__file__).resolve().parent.parent, args.reset)
    except (OSError, ValueError, KeyError, IndexError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'Reset failed: ' + (getattr(error, 'stderr', None) or str(error)) + '\n')


if __name__ == '__main__':
    main()
