"""Manual reset must preserve backups and refuse unsafe bind directories."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reset_jenkins', ROOT / 'scripts/reset-jenkins.py')
reset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reset)


class ResetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.home = self.root / 'jenkins_home'
        self.plugins = self.root / 'plugins'
        self.home.mkdir()
        self.plugins.mkdir()
        (self.home / 'config.xml').write_text('original auth and settings')
        (self.plugins / 'example.jpi').write_text('original plugin')
        (self.root / 'env.conf').write_text('original env')
        (self.root / 'ssl').mkdir()
        (self.root / 'ssl/key').write_text('original ssl')
        self.calls = []

    def info(self):
        return {'Mounts': [{'Type': 'bind', 'Destination': destination, 'Source': str(path)}
                           for destination, path in zip(reset.DESTINATIONS, (self.home, self.plugins))]}

    def podman(self, *args):
        self.calls.append(args)
        return json.dumps([self.info()]) if args[0] == 'inspect' else ''

    def test_preview_does_not_stop_or_move_data(self):
        with patch.object(reset, 'podman', side_effect=self.podman):
            reset.reset(self.root)
        self.assertEqual([call[0] for call in self.calls], ['inspect'])
        self.assertEqual((self.home / 'config.xml').read_text(), 'original auth and settings')
        self.assertFalse(list(self.root.glob('*.backup-*')))

    def test_reset_keeps_full_backups_env_and_ssl(self):
        with patch.object(reset, 'podman', side_effect=self.podman):
            reset.reset(self.root, True)
        self.assertEqual([call[0] for call in self.calls], ['inspect', 'stop', 'rm'])
        self.assertEqual(list(self.home.iterdir()), [])
        self.assertEqual(list(self.plugins.iterdir()), [])
        backup = next(self.root.glob('jenkins_home.backup-*'))
        self.assertEqual((backup / 'config.xml').read_text(), 'original auth and settings')
        self.assertEqual((next(self.root.glob('plugins.backup-*')) / 'example.jpi').read_text(), 'original plugin')
        self.assertEqual((self.root / 'env.conf').read_text(), 'original env')
        self.assertEqual((self.root / 'ssl/key').read_text(), 'original ssl')

    def test_nested_plugins_are_backed_up_with_home(self):
        self.plugins.rename(self.home / 'nested')
        self.plugins = self.home / 'nested'
        with patch.object(reset, 'podman', side_effect=self.podman):
            reset.reset(self.root, True)
        backups = list(self.root.glob('*.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / 'nested/example.jpi').read_text(), 'original plugin')
        self.assertEqual(list(self.plugins.iterdir()), [])

    def test_failure_restores_data_and_keeps_container(self):
        def fail(*args):
            result = self.podman(*args)
            if args[0] == 'rm':
                raise subprocess.CalledProcessError(1, 'podman rm')
            return result
        with patch.object(reset, 'podman', side_effect=fail):
            with self.assertRaises(subprocess.CalledProcessError):
                reset.reset(self.root, True)
        self.assertEqual((self.home / 'config.xml').read_text(), 'original auth and settings')
        self.assertEqual((self.plugins / 'example.jpi').read_text(), 'original plugin')
        self.assertFalse(list(self.root.glob('*.backup-*')))

    def test_project_root_and_symlinks_are_refused_before_stop(self):
        for path in (self.root, self.root / 'linked'):
            if path.name == 'linked':
                path.symlink_to(self.home, target_is_directory=True)
            self.home = path
            with patch.object(reset, 'podman', side_effect=self.podman):
                with self.assertRaises(ValueError):
                    reset.reset(self.root, True)
        self.assertTrue(all(call[0] == 'inspect' for call in self.calls))


if __name__ == '__main__':
    unittest.main()
