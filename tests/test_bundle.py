"""Negative tests for the plugin supply-chain boundary. Fixtures are not real plugins."""
import hashlib
import io
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('bundle', Path(__file__).parents[1] / 'scripts/bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.custom = self.root / 'custom-plugins'
        self.custom.mkdir()
        self.lock = self.root / 'plugins.lock.json'
        self.patch = patch.multiple(bundle, ROOT=self.root, CUSTOM=self.custom, LOCK=self.lock)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        (self.root / 'plugins.txt').write_text('official:1.0\n')
        (self.root / 'Containerfile').write_text('FROM docker.io/jenkins/jenkins:2.580.2-lts-jdk25@sha256:' + 'a' * 64 + '\n')
        self.data = {'core': '2.580.2', 'requested': {'official': '1.0'},
                     'plugins': {'official': {'version': '1.0', 'sha256': 'a' * 64}}}
        self.write_lock()

    def write_lock(self):
        self.lock.write_text(json.dumps(self.data))

    def artifact(self, name, filename=None, dependency=''):
        path = self.custom / (filename or (name + '.hpi'))
        content = (f'Manifest-Version: 1.0\r\nShort-Name: {name}\r\nPlugin-Version: 1.0\r\n'
                   f'Jenkins-Version: 2.528.3\r\nPlugin-Dependencies: {dependency}\r\n\r\n')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', content)
        return path

    def all_artifacts(self):
        for name in ['im-sync', 'eai-login', 'org-sync']:
            self.artifact(name)

    def test_custom_plugins_are_optional(self):
        bundle.prepare(None)
        self.assertEqual(list((self.root / 'build/custom').iterdir()), [])

    def test_duplicate_ids_across_extensions_are_rejected(self):
        self.artifact('im-sync')
        self.artifact('im-sync', 'replacement.jpi')
        with self.assertRaisesRegex(ValueError, 'Duplicate custom'):
            bundle.custom_plugins()

    def test_dependency_not_in_lock_is_rejected(self):
        self.all_artifacts()
        self.artifact('extra', dependency='missing-api:1.0')
        with self.assertRaisesRegex(ValueError, 'requires unlocked missing-api'):
            bundle.prepare(None)

    def test_official_custom_collision_is_rejected(self):
        self.all_artifacts()
        self.artifact('official')
        with self.assertRaisesRegex(ValueError, 'collision'):
            bundle.prepare(None)

    def test_changed_requested_version_invalidates_lock(self):
        (self.root / 'plugins.txt').write_text('official:2.0\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            bundle.prepare(None)

    def test_manual_from_change_invalidates_old_core_lock(self):
        path = self.root / 'Containerfile'
        path.write_text(path.read_text().replace('2.580.2-lts', '2.999.1-lts'))
        self.assertEqual(bundle.target_core(), '2.999.1')
        with self.assertRaisesRegex(ValueError, 'changed'):
            bundle.prepare(None)

    def test_unpinned_base_image_is_rejected(self):
        (self.root / 'Containerfile').write_text('FROM docker.io/jenkins/jenkins:lts-jdk25\n')
        with self.assertRaisesRegex(ValueError, 'verified digest'):
            bundle.target_core()

    def test_staging_uses_manifest_id_and_actual_checksum(self):
        self.all_artifacts()
        original = self.artifact('new-plugin', 'arbitrary-filename.jpi', 'official:1.0')
        bundle.prepare(None)
        staged = self.root / 'build/custom/new-plugin.jpi'
        self.assertEqual(original.read_bytes(), staged.read_bytes())
        sums = (self.root / 'build/plugins.sha256').read_text()
        self.assertIn(hashlib.sha256(staged.read_bytes()).hexdigest() + '  new-plugin.jpi', sums)
        self.assertIn('a' * 64 + '  official.jpi', sums)
        self.assertEqual((self.root / 'build/jenkins-core-version').read_text(), '2.580.2\n')

    def test_manifest_continuation_is_unfolded(self):
        path = self.custom / 'folded.hpi'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF',
                             'Short-Name: folded\r\nPlugin-Version: 1.0\r\nJenkins-Version: 2.528.3\r\n'
                             'Plugin-Dependencies: first:1.0,\r\n second:2.0\r\n\r\n')
        self.assertEqual(list(bundle.dependencies(bundle.manifest(path))), [['first', '1.0'], ['second', '2.0']])

    def test_export_verifies_plugin_and_leaves_image_and_live_home_unchanged(self):
        artifact = self.artifact('official')
        body = artifact.read_bytes()
        artifact.unlink()
        self.data['plugins']['official'].update(sha256=hashlib.sha256(body).hexdigest(), url='https://example.test/plugin.hpi')
        self.write_lock()
        (self.root / 'plugins').mkdir()
        marker = self.root / 'plugins/live-marker'
        marker.write_text('preserve')
        before = (self.root / 'Containerfile').read_bytes()
        with patch.object(bundle, 'urlopen', return_value=io.BytesIO(body)):
            bundle.export_plugins(None)
        self.assertEqual((self.root / 'build/plugin-bundle/official.jpi').read_bytes(), body)
        self.assertEqual(marker.read_text(), 'preserve')
        self.assertEqual((self.root / 'Containerfile').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
