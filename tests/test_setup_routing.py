"""Opt-in HTTP regression against a disposable Jenkins, before or after setup."""
import http.cookiejar
import os
import unittest
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

BASE_URL = os.environ.get('JENKINS_SETUP_TEST_URL', '').rstrip('/')
PASSWORD_FILE = os.environ.get('JENKINS_SETUP_TEST_PASSWORD_FILE', '')
COMPLETE = os.environ.get('JENKINS_SETUP_TEST_COMPLETE') == '1'


class LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.inputs = {}

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == 'form' and self.action is None:
            self.action = attributes.get('action')
        ignored_types = ('checkbox', 'radio', 'submit', 'button', 'file')
        if tag == 'input' and attributes.get('name') and attributes.get('type') not in ignored_types:
            self.inputs[attributes['name']] = attributes.get('value', '')


@unittest.skipUnless(BASE_URL and PASSWORD_FILE, 'Requires an explicitly selected disposable Jenkins')
class SetupRoutingTests(unittest.TestCase):
    def test_login_targets_and_api_access(self):
        parsed = urllib.parse.urlsplit(BASE_URL)
        self.assertIn(parsed.hostname, ('127.0.0.1', 'localhost', '::1'))
        context = parsed.path
        password = Path(PASSWORD_FILE).read_text().strip()
        for target in ('/', '/manage/', '/manage/appearance/'):
            with self.subTest(target=target, complete=COMPLETE):
                client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
                client.addheaders = [('Accept', 'text/html')]
                response = client.open(BASE_URL + '/login?' + urllib.parse.urlencode({'from': context + target}), timeout=30)
                form = LoginForm()
                form.feed(response.read().decode())
                self.assertTrue(form.action)
                form.inputs.update(j_username='admin', j_password=password)
                response = client.open(urllib.parse.urljoin(response.url, form.action),
                                       urllib.parse.urlencode(form.inputs).encode(), timeout=30)
                body = response.read().decode()
                if COMPLETE:
                    self.assertEqual(response.url, BASE_URL + target)
                    self.assertNotIn('class="plugin-setup-wizard-container"', body)
                else:
                    expected = BASE_URL + ('/' if target == '/' else '/setupWizard/')
                    self.assertEqual(response.url, expected)
                    self.assertIn('class="plugin-setup-wizard-container"', body)
                # Non-HTML management requests must retain Core's ordinary routing.
                request = urllib.request.Request(BASE_URL + '/manage/appearance/',
                                                 headers={'Accept': 'application/json'})
                ordinary = client.open(request, timeout=30)
                self.assertEqual(ordinary.url, BASE_URL + '/manage/appearance/')
                request = urllib.request.Request(BASE_URL + '/api/json',
                                                 headers={'Accept': 'application/json'})
                api = client.open(request, timeout=30)
                self.assertEqual(api.status, 200)
                self.assertIn('application/json', api.headers.get('Content-Type', ''))
        with self.assertRaises(urllib.error.HTTPError) as denied:
            urllib.request.urlopen(BASE_URL + '/api/json', timeout=30)
        self.assertEqual(denied.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
