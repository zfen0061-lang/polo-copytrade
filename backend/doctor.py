"""Fast local file checks. Never launches a driver, opens the network or connects an account."""
from __future__ import annotations

import argparse
import importlib.util
from importlib import metadata
import json
import os
from pathlib import Path
import sys

from .paths import VERSION


def browser_files(package_root, cache_root, platform=None):
    platform = platform or sys.platform
    manifest = json.loads((package_root / 'driver' / 'package' / 'browsers.json').read_text(encoding='utf-8'))
    revisions = {item['name']: str(item['revision']) for item in manifest['browsers']}
    chromium = cache_root / ('chromium-' + revisions['chromium'])
    shell = cache_root / ('chromium_headless_shell-' + revisions['chromium-headless-shell'])
    if platform == 'win32':
        full = [chromium / 'chrome-win64' / 'chrome.exe', chromium / 'chrome-win' / 'chrome.exe']
        headless = [shell / 'chrome-headless-shell-win64' / 'chrome-headless-shell.exe',
                    shell / 'chrome-win' / 'headless_shell.exe']
    elif platform == 'darwin':
        full = [chromium / 'chrome-mac' / 'Chromium.app' / 'Contents' / 'MacOS' / 'Chromium',
                chromium / 'chrome-mac-arm64' / 'Google Chrome for Testing.app' / 'Contents' / 'MacOS' / 'Google Chrome for Testing',
                chromium / 'chrome-mac-x64' / 'Google Chrome for Testing.app' / 'Contents' / 'MacOS' / 'Google Chrome for Testing']
        headless = [shell / 'chrome-mac' / 'headless_shell',
                    shell / 'chrome-headless-shell-mac-arm64' / 'chrome-headless-shell',
                    shell / 'chrome-headless-shell-mac-x64' / 'chrome-headless-shell']
    else:
        full = [chromium / 'chrome-linux' / 'chrome', chromium / 'chrome-linux64' / 'chrome']
        headless = [shell / 'chrome-linux' / 'headless_shell', shell / 'chrome-headless-shell-linux64' / 'chrome-headless-shell']
    return any(path.is_file() for path in full) and any(path.is_file() for path in headless)


def browser_cache(package_root):
    configured = os.environ.get('PLAYWRIGHT_BROWSERS_PATH')
    if configured == '0':
        return package_root / 'driver' / 'package' / '.local-browsers'
    if configured:
        return Path(configured).expanduser().resolve()
    if sys.platform == 'win32':
        return Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'ms-playwright'
    if sys.platform == 'darwin':
        return Path.home() / 'Library' / 'Caches' / 'ms-playwright'
    return Path(os.environ.get('XDG_CACHE_HOME') or Path.home() / '.cache') / 'ms-playwright'


def collector_status():
    result = dict(installed=False, chromium=False, error='', missing_packages=[])
    try:
        spec = importlib.util.find_spec('playwright')
        if spec is None or not spec.origin:
            return result
        result['installed'] = True
        dependencies=['greenlet']
        if any(item.lower().startswith('pyee') for item in (metadata.requires('playwright') or [])):
            dependencies.append('pyee')
        result['missing_packages'] = [name for name in dependencies if importlib.util.find_spec(name) is None]
        if result['missing_packages']:
            result['error'] = 'MissingDependencies: ' + ', '.join(result['missing_packages'])
        package_root = Path(spec.origin).parent
        result['chromium'] = browser_files(package_root, browser_cache(package_root))
    except Exception as error:
        result['error'] = type(error).__name__
    return result


def inspect_setup():
    collector = collector_status()
    python_ok = sys.version_info >= (3, 10)
    return dict(
        version=VERSION, python=sys.version.split()[0], python_ok=python_ok,
        dashboard_ready=python_ok, collector=collector,
        collection_ready=python_ok and collector['installed'] and collector['chromium'] and not collector['error'],
        online_verified=False,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local file check; never connects or trades')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    status = inspect_setup()
    if args.json:
        print(json.dumps(status, ensure_ascii=True))
    else:
        print('Polo CopyTrade ' + VERSION + ' - local setup check')
        print('Python:', status['python'], 'OK' if status['python_ok'] else '3.10+ REQUIRED')
        print('Dashboard:', 'READY' if status['dashboard_ready'] else 'NOT READY')
        print('Playwright:', 'INSTALLED' if status['collector']['installed'] else 'MISSING')
        print('Chromium and headless shell:', 'FOUND' if status['collector']['chromium'] else 'MISSING')
        if status['collector']['error']:
            print('Collector check:', status['collector']['error'])
        print('Public/account collection:', 'READY FOR ONLINE VERIFICATION' if status['collection_ready'] else 'SETUP REQUIRED')
        if not status['collection_ready']:
            print('Source users: run setup.cmd, then check.cmd. Packaged users: extract the complete release folder.')
        print('No account connected and no order sent by this check.')
    return 0 if status['collection_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
