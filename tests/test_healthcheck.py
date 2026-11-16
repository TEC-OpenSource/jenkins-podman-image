"""Probe behavior without credentials, remote traffic or dependencies."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HealthcheckTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        fake = self.directory / 'curl'
        fake.write_text('#!/usr/bin/env python3\n'
                        'import json,os,sys\n'
                        'from pathlib import Path\n'
                        'Path(os.environ["CURL_ARGUMENTS"]).write_text(json.dumps(sys.argv[1:]))\n'
                        'print(os.environ["CURL_STATUS"],end="")\n'
                        'sys.exit(int(os.environ.get("CURL_EXIT","0")))\n')
        fake.chmod(0o700)

    def probe(self, status='200', **values):
        env = dict(os.environ)
        for key in ('JENKINS_HEALTH_SCHEME', 'JENKINS_HEALTH_PORT', 'JENKINS_HEALTH_PATH'):
            env.pop(key, None)
        env.update(PATH=str(self.directory) + os.pathsep + env['PATH'], CURL_STATUS=status,
                   CURL_ARGUMENTS=str(self.directory / 'arguments.json'))
        env.update(values)
        return subprocess.run(['sh', str(ROOT / 'scripts/healthcheck.sh')], env=env,
                              text=True, capture_output=True)

    def test_authentication_responses_are_live_without_following_redirects(self):
        for status in ('200', '301', '302', '303', '307', '308', '401', '403'):
            with self.subTest(status=status):
                self.assertEqual(self.probe(status).returncode, 0)
        arguments = json.loads((self.directory / 'arguments.json').read_text())
        self.assertEqual(arguments[-1], 'http://127.0.0.1:8080/login')
        self.assertIn('--noproxy', arguments)
        self.assertIn('*', arguments)
        self.assertIn('--max-time', arguments)
        for forbidden in ('--location', '-L', '--user', '--insecure'):
            self.assertNotIn(forbidden, arguments)

    def test_startup_server_errors_and_connection_failures_are_unhealthy(self):
        for status in ('000', '404', '500', '502', '503'):
            with self.subTest(status=status):
                self.assertNotEqual(self.probe(status).returncode, 0)
        self.assertNotEqual(self.probe('200', CURL_EXIT='28').returncode, 0)

    def test_https_stays_on_loopback_and_supports_a_context_path(self):
        self.assertEqual(self.probe(JENKINS_HEALTH_SCHEME='https', JENKINS_HEALTH_PORT='8443',
                                    JENKINS_HEALTH_PATH='/jenkins/login').returncode, 0)
        arguments = json.loads((self.directory / 'arguments.json').read_text())
        self.assertEqual(arguments[-1], 'https://127.0.0.1:8443/jenkins/login')
        self.assertIn('--insecure', arguments)

    def test_invalid_endpoint_settings_are_rejected_before_curl(self):
        for values in ({'JENKINS_HEALTH_SCHEME': 'file'}, {'JENKINS_HEALTH_PORT': '0'},
                       {'JENKINS_HEALTH_PORT': '65536'}, {'JENKINS_HEALTH_PORT': '8080 --user secret'},
                       {'JENKINS_HEALTH_PATH': 'https://example.com'}):
            with self.subTest(values=values):
                self.assertNotEqual(self.probe(**values).returncode, 0)
        self.assertFalse((self.directory / 'arguments.json').exists())


if __name__ == '__main__':
    unittest.main()
