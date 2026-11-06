"""Packaging boundary tests. Podman is mocked; no real images or secrets in fixtures."""
import hashlib
import importlib.util
import io
import json
import shutil
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_deploy', ROOT / 'scripts/package-deploy.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)
IMAGE = 'localhost/jenkins-25:package-test-amd64'


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'source'
        self.output = Path(self.temporary.name) / 'output with spaces'
        self.root.mkdir()
        for name in package.INPUTS:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        (self.root / 'env').write_text('DO_NOT_PACKAGE_LIVE_ENV')
        for name in ('ssl/private.key', 'plugins/live-marker', 'jenkins_home/users/config.xml'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('DO_NOT_PACKAGE_LIVE_DATA')
        self.info = {'Id': 'a' * 64, 'Os': 'linux', 'Architecture': 'amd64', 'RepoTags': [IMAGE],
                     'Config': {'Env': ['JENKINS_VERSION=2.580.2', 'JAVA_VERSION=jdk-25.0.5+8',
                                        'JENKINS_JAVA_OPTS=-Dhudson.model.UpdateCenter.updateCenterUrl=file:/opt/jenkins-offline/']}}
        self.calls = []

    def podman(self, *args):
        self.calls.append(args)
        if args[:2] == ('image', 'inspect'):
            return json.dumps([self.info])
        if args[0] == 'save':
            target = Path(args[args.index('--output') + 1])
            # Minimal mock OCI transport, not a deployable image.
            with tarfile.open(target, 'w') as archive:
                body = b'{"imageLayoutVersion":"1.0.0"}'
                item = tarfile.TarInfo('oci-layout')
                item.size = len(body)
                archive.addfile(item, io.BytesIO(body))
            return ''
        raise AssertionError('Unexpected Podman mutation: ' + repr(args))

    def make(self):
        with patch.object(package, 'podman', side_effect=self.podman):
            return package.make_package(self.root, self.output, IMAGE)

    def test_package_is_complete_and_excludes_live_files(self):
        result = self.make()
        self.assertEqual(result.name, 'jenkins-podman-jdk25.tar')
        prefix = 'jenkins-podman-jdk25/'
        with tarfile.open(result) as archive:
            names = set(archive.getnames())
            for name in ['env.example', 'podman-compose.yml', 'podman-compose-https.yml', 'README.txt',
                         'IMAGE.txt', 'SHA256SUMS', 'ssl', 'plugins', 'jenkins_home', 'archives',
                         'ssl/https.properties.example', 'archives/jenkins-25-amd64.oci.tar']:
                self.assertIn(prefix + name, names)
            self.assertIn(prefix + 'scripts/reset-jenkins.py', names)
            self.assertIn(prefix + 'offline-update-center.xml', names)
            for name in ['env', 'ssl/private.key', 'plugins/live-marker', 'jenkins_home/users/config.xml']:
                self.assertNotIn(prefix + name, names)
            env = archive.extractfile(prefix + 'env.example').read().decode()
            self.assertIn('JENKINS_IMAGE=' + IMAGE, env)
            self.assertIn('JENKINS_SSL_DIR=./ssl', env)
            compose = archive.extractfile(prefix + 'podman-compose.yml').read().decode()
            self.assertIn('${JENKINS_IMAGE:-' + IMAGE + '}', compose)
            readme = archive.extractfile(prefix + 'README.txt').read().decode()
            self.assertNotIn('@@', readme)
            self.assertIn('podman load --input jenkins-25-amd64.oci.tar', readme)
            self.assertIn('\npodman-compose --env-file env -f podman-compose.yml up --no-build -d\n', readme)
            self.assertFalse(any(line[:1].isspace() for line in readme.splitlines() if line))
            for line in archive.extractfile(prefix + 'SHA256SUMS').read().decode().splitlines():
                expected, name = line.split('  ', 1)
                self.assertEqual(hashlib.sha256(archive.extractfile(prefix + name).read()).hexdigest(), expected)
            self.assertTrue(all(not m.name.startswith('/') and '..' not in Path(m.name).parts for m in archive))
        checksum = result.with_name(result.name + '.sha256').read_text().split()[0]
        self.assertEqual(package.sha256(result), checksum)
        self.assertTrue(all(call[0] in ('image', 'save') for call in self.calls))
        self.assertEqual((self.root / 'env').read_text(), 'DO_NOT_PACKAGE_LIVE_ENV')

    def test_wrong_architecture_is_rejected_before_export(self):
        self.info['Architecture'] = 'arm64'
        with self.assertRaisesRegex(ValueError, 'expected linux/amd64'):
            self.make()
        self.assertFalse(any(call[0] == 'save' for call in self.calls))
        self.assertFalse(self.output.exists())

    def test_old_image_without_offline_catalog_is_rejected(self):
        self.info['Config']['Env'] = ['JENKINS_VERSION=2.580.2']
        with self.assertRaisesRegex(ValueError, 'rebuild'):
            self.make()
        self.assertFalse(any(call[0] == 'save' for call in self.calls))

    def test_image_tag_change_does_not_replace_previous_package(self):
        self.output.mkdir()
        previous = self.output / 'jenkins-podman-jdk25.tar'
        previous.write_text('previous valid package')
        def changed(*args):
            result = self.podman(*args)
            if args[0] == 'save':
                self.info['Id'] = 'b' * 64
            return result
        # First inspect must serialize the original object before the mutation.
        with patch.object(package, 'podman', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'tag changed'):
                package.make_package(self.root, self.output, IMAGE)
        self.assertEqual(previous.read_text(), 'previous valid package')
        self.assertFalse(any(self.output.glob('.package-*')))

    def test_symlink_input_is_rejected(self):
        path = self.root / 'env.example'
        path.unlink()
        path.symlink_to(self.root / 'env')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            self.make()
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    unittest.main()
