#!/usr/bin/env python3
"""Small Linux admin monitor. Standard library only; secrets live in RAM."""
import argparse
import fcntl
import hmac
import http.server
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parent
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/tmp/myscoutee-admin-{os.getuid()}')) / 'myscoutee-admin'
CONFIG = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'myscoutee-admin'


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise RuntimeError('Unsafe application directory')
    path.chmod(0o700)


def save_json(path, value):
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(value, output)
    os.replace(temp, path)


def load_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def validate_url(value):
    parsed = urllib.parse.urlsplit(str(value).strip().rstrip('/'))
    if not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('invalid_url')
    local = parsed.hostname == 'localhost'
    try:
        local = local or ipaddress.ip_address(parsed.hostname).is_loopback
    except ValueError:
        pass
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and local):
        raise ValueError('https_required')
    if any(ord(char) < 33 for char in str(value).strip()):
        raise ValueError('invalid_url')
    return parsed.geturl()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward a credential to another endpoint.


def overview(url, key, client_id, demo=False):
    headers = {'Authorization': 'Bearer ' + key, 'X-MyScoutee-Client-Id': client_id, 'Accept': 'application/json'}
    if demo:
        headers['X-App-Session-Kind'] = 'demo'
    request = urllib.request.Request(url + '/overview', headers=headers)
    with urllib.request.build_opener(NoRedirect).open(request, timeout=15) as response:
        content = response.read(65537)
        if len(content) > 65536:
            raise ValueError('response_too_large')
        data = json.loads(content)
        if not isinstance(data.get('statistics'), dict) or not isinstance(data.get('attention'), dict):
            raise ValueError('invalid_response')
        return data


def changed_attention(previous, current):
    if previous is None:
        return False
    old, new = previous.get('attention', {}), current.get('attention', {})
    return ((new.get('unreadMessages', 0) > 0 and bool(new.get('unreadVersion')) and str(new.get('unreadVersion')) > str(old.get('unreadVersion') or ''))
            or any(new.get(key, 0) > old.get(key, 0) for key in ('unreadMessages', 'unresolvedReports', 'unresolvedFeedback', 'supportCases', 'failedJobs')))


class Monitor:
    def __init__(self, prefs_path=None, fetch=overview, notify=None):
        self.prefs_path = prefs_path or CONFIG / 'preferences.json'
        self.prefs = load_json(self.prefs_path)
        self.prefs.setdefault('clientId', str(uuid.uuid4()))
        self.prefs.setdefault('url', 'http://localhost/api/admin-client/v1')
        self.prefs.setdefault('interval', 10)
        self.prefs.setdefault('demo', False)
        self.prefs.setdefault('language', 'en')
        self.lock = threading.RLock()
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.key = ''
        self.generation = 0
        self.data = None
        self.baseline = None
        self.error = ''
        self.last_success = None
        self.alert_sequence = 0
        self.fetch = fetch
        self.notify = notify or self.desktop_notification

    def connect(self, values):
        url = validate_url(values.get('url', ''))
        key = str(values.get('key', '')).strip()
        interval = int(values.get('interval', 10))
        if not key or len(key) > 512 or any(ord(c) < 33 for c in key):
            raise ValueError('invalid_key')
        if interval < 5 or interval > 3600:
            raise ValueError('invalid_interval')
        with self.lock:
            self.prefs.update(url=url, interval=interval, demo=bool(values.get('demo')), language='hu' if values.get('language') == 'hu' else 'en')
            save_json(self.prefs_path, self.prefs)
            self.generation += 1
            self.key = key
            self.data = self.baseline = None
            self.last_success = None
            self.error = ''
            self.alert_sequence = 0
        self.wake.set()

    def configure_interval(self, values):
        interval = int(values.get('interval', 10))
        if interval < 5 or interval > 3600:
            raise ValueError('invalid_interval')
        with self.lock:
            self.prefs.update(interval=interval, language='hu' if values.get('language') == 'hu' else 'en')
            save_json(self.prefs_path, self.prefs)
        self.wake.set()

    def disconnect(self):
        with self.lock:
            self.generation += 1
            self.key = ''
            self.data = self.baseline = None
            self.error = ''
            self.last_success = None
            self.alert_sequence = 0
        self.wake.set()

    def state(self):
        with self.lock:
            return {'connected': bool(self.key), 'preferences': {k: v for k, v in self.prefs.items() if k != 'clientId'},
                    'data': self.data, 'error': self.error, 'lastSuccess': self.last_success, 'alertSequence': self.alert_sequence}

    def poll_once(self):
        with self.lock:
            key, generation, prefs = self.key, self.generation, dict(self.prefs)
        if not key:
            return
        try:
            result = self.fetch(prefs['url'], key, prefs['clientId'], prefs['demo'])
        except Exception as failure:
            with self.lock:
                if generation != self.generation:
                    return
                unauthorized = isinstance(failure, urllib.error.HTTPError) and failure.code in (401, 403)
                self.error = 'authorization_failed' if unauthorized else 'connection_failed'
                if unauthorized:
                    self.key = ''
                    self.data = self.baseline = None
            return
        with self.lock:
            if generation != self.generation:
                return
            changed = changed_attention(self.baseline, result)
            self.data = self.baseline = result
            self.error = ''
            self.last_success = time.time()
            if changed:
                self.alert_sequence += 1
                self.notify(prefs['language'])

    def desktop_notification(self, language):
        if shutil.which('notify-send'):
            message = 'Új adminisztrátori teendő. Nyisd meg a MyScoutee-t.' if language == 'hu' else 'New admin activity. Open MyScoutee to review.'
            try:
                subprocess.run(['notify-send', '--app-name=MyScoutee Admin', '--icon=myscoutee-client-admin',
                                '--hint=string:desktop-entry:myscoutee-client-admin', 'MyScoutee Admin', message],
                               timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def run(self):
        while not self.stopped.is_set():
            self.wake.clear()
            self.poll_once()
            self.wake.wait(self.prefs['interval'] if self.key else 3600)


def handler_for(monitor, control):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def allowed_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def authorized(self):
            return self.allowed_host() and hmac.compare_digest(self.headers.get('X-Monitor-Control', ''), control)

        def reply(self, status, body, content_type='application/json'):
            encoded = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.send_header('Content-Length', str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if not self.allowed_host():
                return self.reply(403, {})
            files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/style.css': ('style.css', 'text/css')}
            if self.path in files:
                name, mime = files[self.path]
                return self.reply(200, (ROOT / name).read_text(), mime)
            if not self.authorized():
                return self.reply(403, {})
            if self.path == '/state':
                return self.reply(200, monitor.state())
            if self.path == '/health':
                return self.reply(200, {'application': 'myscoutee-client-admin'})
            return self.reply(404, {})

        def do_POST(self):
            expected_origin = f'http://127.0.0.1:{self.server.server_port}'
            if not self.authorized() or self.headers.get('Origin', expected_origin) != expected_origin:
                return self.reply(403, {})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0 or length > 4096:
                    return self.reply(413, {})
                values = json.loads(self.rfile.read(length) or b'{}')
                if not isinstance(values, dict):
                    raise ValueError('invalid_request')
                if self.path == '/connect':
                    monitor.connect(values)
                elif self.path == '/interval':
                    monitor.configure_interval(values)
                elif self.path == '/disconnect':
                    monitor.disconnect()
                elif self.path == '/shutdown':
                    monitor.disconnect(); monitor.stopped.set(); monitor.wake.set()
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    return self.reply(404, {})
                return self.reply(200, {})
            except (ValueError, TypeError) as failure:
                return self.reply(400, {'error': str(failure) if str(failure) in ('invalid_url', 'https_required', 'invalid_key', 'invalid_interval') else 'invalid_request'})
    return Handler


def serve():
    private_directory(RUNTIME); private_directory(CONFIG)
    lockfile = open(RUNTIME / 'instance.lock', 'a')
    try:
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return  # Another launcher already owns the one instance.
    control = secrets.token_urlsafe(32)
    monitor = Monitor()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler_for(monitor, control))
    server.daemon_threads = True
    save_json(RUNTIME / 'instance.json', {'port': server.server_port, 'control': control})
    threading.Thread(target=monitor.run, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        monitor.stopped.set(); monitor.disconnect(); server.server_close()
        (RUNTIME / 'instance.json').unlink(missing_ok=True)
        lockfile.close()


def running_instance():
    info = load_json(RUNTIME / 'instance.json')
    try:
        url = f"http://127.0.0.1:{int(info['port'])}/health"
        request = urllib.request.Request(url, headers={'X-Monitor-Control': info['control']})
        with urllib.request.urlopen(request, timeout=1) as response:
            if json.load(response).get('application') == 'myscoutee-client-admin':
                return info
    except (OSError, ValueError, KeyError):
        pass
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-open', action='store_true', help='Start/attach without opening the browser')
    args = parser.parse_args()
    if args.serve:
        return serve()
    private_directory(RUNTIME); private_directory(CONFIG)
    info = running_instance()
    if args.stop:
        if info:
            request = urllib.request.Request(f"http://127.0.0.1:{info['port']}/shutdown", data=b'{}', headers={'X-Monitor-Control': info['control']})
            urllib.request.urlopen(request, timeout=3).close()
        return
    if not info:
        subprocess.Popen([sys.executable, str(ROOT / 'admin_monitor.py'), '--serve'], start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            time.sleep(.05)
            info = running_instance()
            if info:
                break
    if not info:
        raise SystemExit('Could not start MyScoutee Admin monitor')
    if not args.no_open:
        url = f"http://127.0.0.1:{info['port']}/#control={info['control']}"
        browser = next((shutil.which(name) for name in ('google-chrome', 'chromium', 'chromium-browser') if shutil.which(name)), None)
        command = [browser, '--app=' + url] if browser else ['xdg-open', url]
        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
