"""Exercise the built image, read-only source mounting, refresh and persistence."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

image = sys.argv[1] if len(sys.argv) > 1 else 'codeatlas:test'
name = 'codeatlas-test-' + uuid.uuid4().hex[:12]
volume = name + '-data'
base = 'http://127.0.0.1:8081/api/'


def docker(*args):
    return subprocess.run(['docker', *args], check=True, capture_output=True, text=True).stdout


def api(path, payload=None):
    request = urllib.request.Request(base + path, headers={'Content-Type': 'application/json'},
        data=None if payload is None else json.dumps(payload).encode())
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def start(root):
    docker('run', '-d', '--name', name, '-p', '127.0.0.1:8081:8081', '-v', volume + ':/data', '-v', str(root) + ':/repo:ro', image)
    for _ in range(60):
        try:
            if api('health')['status'] == 'ok':
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError('Container did not become healthy: ' + docker('logs', name))


with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    root.chmod(0o755)
    (root / 'a.py').write_text('def alpha():\n    return 1\ndef caller():\n    return alpha()\n')
    try:
        docker('run', '--rm', '-v', volume + ':/data', '-v', str(root) + ':/repo:ro', image, 'index', '/repo')
        start(root)
        assert api('search', {'question': 'alpha'})['hits']
        assert api('impact', {'symbol': 'a.alpha'})['affected'][0]['qualified'] == 'a.caller'
        (root / 'b.py').write_text('def durabilitytest():\n    return 42\n')
        assert api('reindex', {})['changed_files'] == 1
        assert api('search', {'question': 'durabilitytest'})['hits']
        docker('rm', '-f', name)
        start(root)
        assert api('search', {'question': 'durabilitytest'})['hits']
        (root / 'b.py').unlink()
        assert api('reindex', {})['deleted_files'] == 1
        assert not api('search', {'question': 'durabilitytest'})['hits']
        print('PASS: image startup, mounted repository, graph, refresh, persistence across container replacement, deletion')
    finally:
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True)
        subprocess.run(['docker', 'volume', 'rm', volume], capture_output=True)
