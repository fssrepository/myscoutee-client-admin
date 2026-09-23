import json
from pathlib import Path
import tempfile
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import Mock, patch
import admin_monitor as app


def snapshot(unread=0, version='', reports=0):
    return {'statistics': {'ready': True, 'activeProfiles': 4}, 'attention': {'unreadMessages': unread, 'unreadVersion': version, 'unresolvedReports': reports}}


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'prefs.json'
        self.fetch = Mock(return_value=snapshot())
        self.notify = Mock()
        self.monitor = app.Monitor(self.path, self.fetch, self.notify)

    def connect(self):
        self.monitor.connect({'url': 'http://localhost/api/admin-client/v1', 'key': 'secret-key', 'interval': 10})

    def test_connection_preferences_never_store_or_return_key(self):
        self.connect(); self.monitor.poll_once()
        self.assertNotIn('secret-key', self.path.read_text())
        self.assertNotIn('secret-key', json.dumps(self.monitor.state()))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.monitor.state()['connected'])
        self.monitor.disconnect(); self.monitor.poll_once()
        self.assertFalse(self.monitor.state()['connected'])
        self.assertIsNone(self.monitor.state()['data'])
        self.fetch.assert_called_once()

    def test_key_preview_is_masked_and_clears_on_disconnect_or_revocation(self):
        key = 'qa-prefix-12-rest-of-private-key'
        self.monitor.connect({'url': 'http://localhost/api/admin-client/v1', 'key': key, 'interval': 10})
        self.assertEqual(self.monitor.state()['keyPreview'], key[:12] + '…')
        self.assertNotIn(key, json.dumps(self.monitor.state()))
        self.assertNotIn(key[:12], self.path.read_text())
        self.monitor.disconnect()
        self.assertEqual(self.monitor.state()['keyPreview'], '')
        self.monitor.connect({'url': 'http://localhost/api/admin-client/v1', 'key': key, 'interval': 10})
        self.fetch.side_effect = urllib.error.HTTPError('http://localhost', 401, '', {}, None)
        self.monitor.poll_once()
        self.assertEqual(self.monitor.state()['keyPreview'], '')

    def test_short_invalid_credentials_are_never_exposed_by_preview(self):
        self.connect()
        self.assertEqual(self.monitor.state()['keyPreview'], '••••')
        self.assertNotIn('secret-key', json.dumps(self.monitor.state()))

    def test_ubuntu_notification_identity_and_disconnect(self):
        self.monitor.notify = self.monitor.desktop_notification
        with patch.object(app.shutil, 'which', return_value='/usr/bin/notify-send'), patch.object(app.subprocess, 'run') as send:
            self.monitor.poll_once()
            send.assert_not_called()
            self.connect()
            self.fetch.side_effect = [snapshot(1, 'a'), snapshot(2, 'b')]
            self.monitor.poll_once(); self.monitor.poll_once()
            command = send.call_args.args[0]
            self.assertIn('--hint=string:desktop-entry:myscoutee-client-admin', command)
            self.assertIn('--icon=myscoutee-client-admin', command)
            self.assertFalse(any('transient' in arg for arg in command))
            self.monitor.disconnect(); self.monitor.poll_once()
            send.assert_called_once()

    def test_new_messages_same_unread_count_notify_once(self):
        self.connect()
        self.fetch.side_effect = [snapshot(1, 'a'), snapshot(1, 'b'), snapshot(1, 'a'), snapshot(0, ''), snapshot(1, 'c')]
        for _ in range(5): self.monitor.poll_once()
        self.assertEqual(self.notify.call_count, 2)

    def test_reports_increase_but_decreases_and_baseline_do_not_notify(self):
        self.connect()
        self.fetch.side_effect = [snapshot(reports=2), snapshot(reports=1), snapshot(reports=3)]
        for _ in range(3): self.monitor.poll_once()
        self.notify.assert_called_once()

    def test_revocation_clears_key_and_stops_polling(self):
        self.connect()
        self.fetch.side_effect = urllib.error.HTTPError('http://localhost', 401, '', {}, None)
        self.monitor.poll_once(); self.monitor.poll_once()
        self.assertEqual(self.monitor.state()['error'], 'authorization_failed')
        self.assertEqual(self.monitor.key, '')
        self.fetch.assert_called_once()

    def test_transient_failure_preserves_last_snapshot_and_retries(self):
        self.connect()
        self.fetch.side_effect = [snapshot(1, 'a'), TimeoutError(), snapshot(1, 'a')]
        self.monitor.poll_once(); self.monitor.poll_once()
        self.assertEqual(self.monitor.state()['data'], snapshot(1, 'a'))
        self.assertEqual(self.monitor.state()['error'], 'connection_failed')
        self.monitor.poll_once(); self.assertEqual(self.monitor.state()['error'], '')

    def test_disconnect_during_request_discards_late_response(self):
        self.connect()
        def late(*args):
            self.monitor.disconnect()
            return snapshot(100, 'late')
        self.fetch.side_effect = late
        self.monitor.poll_once()
        self.assertIsNone(self.monitor.state()['data'])
        self.notify.assert_not_called()

    def test_poll_interval_changes_without_replacing_key(self):
        self.connect(); self.monitor.configure_interval({'interval': 22})
        self.assertEqual(self.monitor.key, 'secret-key')
        self.assertEqual(self.monitor.prefs['interval'], 22)
        for interval in [0, 4, 3601]:
            with self.assertRaises(ValueError): self.monitor.configure_interval({'interval': interval})

    def test_remote_https_and_localhost_only_http(self):
        self.assertEqual(app.validate_url('https://netcup.example/api/admin-client/v1/'), 'https://netcup.example/api/admin-client/v1')
        for url in ['http://netcup.example/api', 'https://user:pass@host/api', 'file:///etc/passwd', 'https://host/api?key=secret', 'https://host/api#key']:
            with self.assertRaises(ValueError): app.validate_url(url)

    def test_local_api_requires_control_token_and_same_origin(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), app.handler_for(self.monitor, 'control'))
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        base = f'http://127.0.0.1:{server.server_port}'
        with self.assertRaises(urllib.error.HTTPError) as denied: urllib.request.urlopen(base + '/state')
        self.assertEqual(denied.exception.code, 403)
        request = urllib.request.Request(base + '/disconnect', data=b'{}', headers={'X-Monitor-Control':'control','Origin':'https://evil.invalid'})
        with self.assertRaises(urllib.error.HTTPError) as denied: urllib.request.urlopen(request)
        self.assertEqual(denied.exception.code, 403)
        request = urllib.request.Request(base + '/state', headers={'X-Monitor-Control':'control'})
        with urllib.request.urlopen(request) as response: self.assertFalse(json.load(response)['connected'])



class LifecycleTest(unittest.TestCase):
    def test_launcher_reuses_instance_and_attaches_without_resetting_connection(self):
        import os
        import subprocess
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, 'XDG_RUNTIME_DIR': directory + '/runtime', 'XDG_CONFIG_HOME': directory + '/config'}
            command = [sys.executable, str(app.ROOT / 'admin_monitor.py')]
            def run(*args): subprocess.run(command + list(args), env=env, check=True, timeout=10)
            try:
                run('--no-open')
                file = Path(directory) / 'runtime/myscoutee-admin/instance.json'
                first = json.loads(file.read_text())
                base = f"http://127.0.0.1:{first['port']}"
                data = json.dumps({'url':'http://127.0.0.1:1/api/admin-client/v1','key':'temporary-secret','interval':30}).encode()
                request = urllib.request.Request(base+'/connect', data=data, headers={'X-Monitor-Control':first['control']})
                urllib.request.urlopen(request, timeout=2).close()
                run('--no-open')
                self.assertEqual(first, json.loads(file.read_text()))
                with urllib.request.urlopen(urllib.request.Request(base+'/state',headers={'X-Monitor-Control':first['control']})) as response:
                    self.assertTrue(json.load(response)['connected'])
                self.assertNotIn('temporary-secret', (Path(directory)/'config/myscoutee-admin/preferences.json').read_text())
            finally:
                run('--stop')

    def test_api_headers_and_redirect_does_not_forward_credential(self):
        from http.server import BaseHTTPRequestHandler
        calls=[]
        class Api(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self):
                calls.append((self.path,dict(self.headers)))
                if self.path.startswith('/redirect'):
                    self.send_response(302);self.send_header('Location','/leaked');self.end_headers();return
                self.send_response(200);self.end_headers();self.wfile.write(json.dumps(snapshot()).encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Api)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            base=f'http://127.0.0.1:{server.server_port}'
            self.assertIn('statistics',app.overview(base,'secret','identity',True))
            self.assertEqual(calls[0][1]['Authorization'],'Bearer secret')
            self.assertEqual(calls[0][1]['X-App-Session-Kind'],'demo')
            with self.assertRaises(urllib.error.HTTPError):app.overview(base+'/redirect','secret','identity')
            self.assertEqual(len(calls),2)
        finally:
            server.shutdown();server.server_close()

if __name__ == '__main__': unittest.main()
