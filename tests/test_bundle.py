"""Negative tests for the plugin supply-chain boundary. Fixtures are not real plugins."""
import hashlib
import io
import importlib.util
import json
import tempfile
import unittest
from types import SimpleNamespace
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
                     'plugins': {'official': {'version': '1.0', 'sha256': 'a' * 64,
                                              'requiredCore': '2.528.3', 'dependencies': []}}}
        self.write_lock()
        self.war = self.root / 'jenkins.war'
        with zipfile.ZipFile(self.war, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', 'Jenkins-Version: 2.580.2\n\n')
            archive.writestr('WEB-INF/lib/version-number-fixture.jar', b'fixture')
        self.args = SimpleNamespace(war=self.war)
        self.reject_version = None
        self.java_patch = patch.object(bundle.subprocess, 'run', side_effect=self.compare_versions)
        self.java_patch.start()
        self.addCleanup(self.java_patch.stop)

    def compare_versions(self, command, **kwargs):
        # Java's VersionNumber implementation is external; graph tests control only comparison results.
        versions = command[4:]
        pairs = list(zip(versions[::2], versions[1::2]))
        return SimpleNamespace(returncode=0, stdout=''.join(
            ('false' if pair == self.reject_version else 'true') + '\n' for pair in pairs))

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
        bundle.prepare(self.args)
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
            bundle.prepare(self.args)

    def test_official_custom_collision_is_rejected(self):
        self.all_artifacts()
        self.artifact('official')
        with self.assertRaisesRegex(ValueError, 'collision'):
            bundle.prepare(self.args)

    def test_changed_requested_version_invalidates_lock(self):
        (self.root / 'plugins.txt').write_text('official:2.0\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            bundle.prepare(self.args)

    def test_manual_from_change_invalidates_old_core_lock(self):
        path = self.root / 'Containerfile'
        path.write_text(path.read_text().replace('2.580.2-lts', '2.999.1-lts'))
        self.assertEqual(bundle.target_core(), '2.999.1')
        with self.assertRaisesRegex(ValueError, 'changed'):
            bundle.prepare(self.args)

    def test_unpinned_base_image_is_rejected(self):
        (self.root / 'Containerfile').write_text('FROM docker.io/jenkins/jenkins:lts-jdk25\n')
        with self.assertRaisesRegex(ValueError, 'verified digest'):
            bundle.target_core()

    def test_staging_uses_manifest_id_and_actual_checksum(self):
        self.all_artifacts()
        original = self.artifact('new-plugin', 'arbitrary-filename.jpi', 'official:1.0')
        bundle.prepare(self.args)
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
            bundle.export_plugins(self.args)
        self.assertEqual((self.root / 'build/plugin-bundle/official.jpi').read_bytes(), body)
        self.assertEqual(marker.read_text(), 'preserve')
        self.assertEqual((self.root / 'Containerfile').read_bytes(), before)


    def test_empty_plugin_set_needs_no_war_or_java(self):
        (self.root / 'plugins.txt').write_text('')
        self.data.update(requested={}, plugins={})
        self.write_lock()
        with patch.object(bundle.subprocess, 'run') as java:
            bundle.prepare(None)
        java.assert_not_called()
        self.assertEqual(list((self.root / 'build/custom').iterdir()), [])

    def test_requested_pin_must_be_present_in_locked_plugins(self):
        self.data['plugins'] = {}
        self.write_lock()
        with self.assertRaisesRegex(ValueError, 'Requested pin official:1.0 differs from lock'):
            bundle.prepare(self.args)

    def test_legacy_lock_without_dependency_metadata_requires_resolution(self):
        del self.data['plugins']['official']['dependencies']
        self.write_lock()
        with self.assertRaisesRegex(ValueError, 'Missing dependency metadata for official'):
            bundle.prepare(self.args)

    def test_exact_war_core_must_match_containerfile(self):
        with zipfile.ZipFile(self.war, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF', 'Jenkins-Version: 2.528.3\n\n')
            archive.writestr('WEB-INF/lib/version-number-fixture.jar', b'fixture')
        with self.assertRaisesRegex(ValueError, 'Version-check WAR must be Jenkins 2.580.2'):
            bundle.prepare(self.args)

    def test_locked_official_transitive_minimum_is_checked(self):
        self.data['plugins']['official']['dependencies'] = [dict(name='custom', version='2.0', optional=False)]
        self.write_lock()
        self.artifact('custom')
        self.reject_version = ('1.0', '2.0')
        with self.assertRaisesRegex(ValueError, 'official requires custom:2.0; selected 1.0'):
            bundle.prepare(self.args)

    def test_nonempty_set_requires_exact_target_war(self):
        with self.assertRaisesRegex(ValueError, 'require --war'):
            bundle.prepare(None)
        self.war.write_bytes(b'not a WAR')
        with self.assertRaises(zipfile.BadZipFile):
            bundle.prepare(self.args)

    def test_custom_core_above_target_is_rejected_before_staging(self):
        path = self.artifact('custom')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('META-INF/MANIFEST.MF',
                             'Short-Name: custom\nPlugin-Version: 1.0\nJenkins-Version: 2.600.1\n\n')
        self.reject_version = ('2.580.2', '2.600.1')
        with self.assertRaisesRegex(ValueError, 'custom requires newer Jenkins 2.600.1'):
            bundle.prepare(self.args)
        self.assertFalse((self.root / 'build').exists())

    def test_custom_dependency_minimum_is_checked(self):
        self.artifact('custom', dependency='official:2.0')
        self.reject_version = ('1.0', '2.0')
        with self.assertRaisesRegex(ValueError, 'custom requires official:2.0; selected 1.0'):
            bundle.prepare(self.args)

    def test_locked_transitive_missing_dependency_is_rejected(self):
        self.data['plugins']['official']['dependencies'] = [dict(name='missing', version='1.0', optional=False)]
        self.write_lock()
        with self.assertRaisesRegex(ValueError, 'official requires unlocked missing:1.0'):
            bundle.prepare(self.args)

    def test_optional_absent_dependency_is_allowed_but_present_minimum_is_checked(self):
        self.artifact('custom', dependency='missing:1.0;resolution:=optional,official:2.0;resolution:=optional')
        self.reject_version = ('1.0', '2.0')
        with self.assertRaisesRegex(ValueError, 'custom requires official:2.0'):
            bundle.prepare(self.args)
        self.reject_version = None
        bundle.prepare(self.args)

    def test_cyclic_dependencies_are_rejected(self):
        self.artifact('first', dependency='second:1.0')
        self.artifact('second', dependency='first:1.0')
        with self.assertRaisesRegex(ValueError, 'Cyclic plugin dependency'):
            bundle.prepare(self.args)

    def test_invalid_locked_checksum_is_rejected(self):
        self.data['plugins']['official']['sha256'] = 'not-a-checksum'
        self.write_lock()
        with self.assertRaisesRegex(ValueError, 'Invalid SHA-256 lock for official'):
            bundle.prepare(self.args)

    def test_export_rejects_checksum_mismatch_without_publishing_partial_bundle(self):
        self.data['plugins']['official']['url'] = 'https://example.test/official.hpi'
        self.write_lock()
        with patch.object(bundle, 'urlopen', return_value=io.BytesIO(b'wrong bytes')):
            with self.assertRaisesRegex(ValueError, 'Checksum mismatch: official'):
                bundle.export_plugins(self.args)
        self.assertFalse((self.root / 'build/plugin-bundle').exists())

    def test_export_validates_actual_manifest_dependencies_not_only_catalog(self):
        artifact = self.artifact('official', dependency='undeclared-api:1.0')
        body = artifact.read_bytes()
        artifact.unlink()
        self.data['plugins']['official'].update(sha256=hashlib.sha256(body).hexdigest(),
                                               url='https://example.test/official.hpi')
        self.write_lock()
        with patch.object(bundle, 'urlopen', return_value=io.BytesIO(body)):
            with self.assertRaisesRegex(ValueError, 'official requires unlocked undeclared-api:1.0'):
                bundle.export_plugins(self.args)
        self.assertFalse((self.root / 'build/plugin-bundle').exists())

    def test_resolve_rejects_catalog_version_below_required_minimum(self):
        self.artifact('custom', dependency='official:2.0')
        self.reject_version = ('1.0', '2.0')
        catalog = {'plugins': {'official': dict(version='1.0', requiredCore='2.528.3', dependencies=[],
                                               sha256='YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE=')}}
        args = SimpleNamespace(metadata=None, versions=None, war=self.war)
        before = self.lock.read_bytes()
        with patch.object(bundle, 'metadata', return_value=catalog):
            with self.assertRaisesRegex(ValueError, 'custom requires official:2.0'):
                bundle.resolve(args)
        self.assertEqual(before, self.lock.read_bytes())


if __name__ == '__main__':
    unittest.main()
