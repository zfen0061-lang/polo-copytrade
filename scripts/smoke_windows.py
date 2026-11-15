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
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(exe.parent / '_internal/playwright/driver/package/.local-browsers')
            from playwright.sync_api import sync_playwright
            with sync_playwright() as runtime:
                browser = runtime.chromium.launch(headless=True)
                try:
                    page = browser.new_page()
                    page.goto('http://127.0.0.1:18765/', wait_until='domcontentloaded')
                    page.wait_for_function(
                        "Array.from(document.querySelectorAll('.polo-mark, .account-placeholder img')).length >= 2 && "
                        "Array.from(document.querySelectorAll('.polo-mark, .account-placeholder img')).every(i => i.complete && i.naturalWidth > 0)",
                        timeout=15000,
                    )
                    page.locator('.nav-item[data-view="settings"]').click()
                    if not page.locator('#view-settings').is_visible():
                        raise RuntimeError('Packaged navigation did not respond')
                    page.locator('#add-trader').click()
                    if not page.locator('#trader-dialog').is_visible():
                        raise RuntimeError('Packaged trader dialog did not open')
                    page.locator('#close-dialog').click()
                    page.locator('.nav-item[data-view="live"]').click()
                    page.locator('#show-connect-help').click()
                    if not page.locator('#connect-guide').is_visible():
                        raise RuntimeError('Packaged account help did not open')
                    page.locator('#close-connect-guide').click()
                finally:
                    browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    with tempfile.TemporaryDirectory() as folder:
        demo_process=subprocess.Popen([str(exe),'--demo','--preview','--no-browser',
            '--data',str(Path(folder)/'demo/state.sqlite3'),'--source-data',str(Path(folder)/'source/state.sqlite3')],
            env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            end=time.monotonic()+30
            while True:
                if demo_process.poll() is not None:raise RuntimeError('Packaged Demo preview exited early')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:8766/api/demo-v2/state',timeout=2) as response:demo=json.load(response)
                    break
                except (urllib.error.URLError,TimeoutError):
                    if time.monotonic()>=end:raise RuntimeError('Packaged Demo preview did not start')
                    time.sleep(.25)
            if not demo['available'] or demo['configured'] or demo['running'] or demo['production_allowed']:
                raise RuntimeError('Packaged Demo preview must have no credentials, active orders or production capability')
            with urllib.request.urlopen('http://127.0.0.1:8766/',timeout=2) as response:
                if b'FUTURES DEMO' not in response.read():raise RuntimeError('Packaged Demo page missing')
        finally:
            demo_process.terminate()
            try:demo_process.wait(timeout=5)
            except subprocess.TimeoutExpired:demo_process.kill();demo_process.wait()
    print('Packaged browser, account HTTP and credential-free Demo startup checks passed; no exchange orders.')


if __name__ == '__main__':
    main()
