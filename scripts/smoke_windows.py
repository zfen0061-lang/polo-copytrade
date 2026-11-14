"""Exercise the built app, local browser and local HTTP only. Never connects Binance."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    exe = ROOT / 'dist' / 'PoloCopyTrade' / 'PoloCopyTrade.exe'
    env = dict(os.environ)
    for key in ('POLO_BINANCE_API_KEY', 'POLO_BINANCE_API_SECRET'):
        env.pop(key, None)
    subprocess.run([str(exe), '--smoke-test'], env=env, check=True, timeout=90)
    with tempfile.TemporaryDirectory() as folder:
        process = subprocess.Popen([
            str(exe), '--no-browser', '--no-runner', '--port', '18765',
            '--data', str(Path(folder) / 'state.sqlite3'),
        ], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            end = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Packaged server exited before it was ready')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:18765/api/live/state', timeout=2) as response:
                        state = json.load(response)
                    break
                except (urllib.error.URLError, TimeoutError):
                    if time.monotonic() >= end:
                        raise RuntimeError('Packaged server did not become ready')
                    time.sleep(0.25)
            if state['connected'] or state['watching']:
                raise RuntimeError('Packaged app must start disconnected and not following')
            with urllib.request.urlopen('http://127.0.0.1:18765/', timeout=2) as response:
                if b'Polo CopyTrade' not in response.read():
                    raise RuntimeError('Packaged frontend missing')
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    print('Packaged browser and loopback HTTP checks passed; no account/order requests.')


if __name__ == '__main__':
    main()
