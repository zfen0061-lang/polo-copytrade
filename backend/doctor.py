"""Local setup checks only: no network, account requests or order submission."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys


def collector_status():
    try:
        installed = importlib.util.find_spec('playwright') is not None
    except (ImportError, ValueError):
        installed = False
    result = dict(installed=installed, chromium=False, error='')
    if not installed:
        return result
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as runtime:
            # Resolving the expected binary path does not launch a browser or visit a site.
            result['chromium'] = Path(runtime.chromium.executable_path).is_file()
    except Exception as error:
        result['error'] = type(error).__name__
    return result


def inspect_setup():
    collector = collector_status()
    python_ok = sys.version_info >= (3, 10)
    return dict(
        version='0.2.1',
        python=sys.version.split()[0],
        python_ok=python_ok,
        dashboard_ready=python_ok,
        collector=collector,
        collection_ready=python_ok and collector['installed'] and collector['chromium'] and not collector['error'],
        online_verified=False,
    )


def main():
    parser = argparse.ArgumentParser(description='Local setup check; never connects or trades')
    parser.add_argument('--json', action='store_true', help='Machine-readable local setup status')
    args = parser.parse_args()
    status = inspect_setup()
    if args.json:
        print(json.dumps(status, ensure_ascii=True))
    else:
        print('Polo CopyTrade 0.2.1 - local setup check')
        print('Python:', status['python'], 'OK' if status['python_ok'] else '3.10+ REQUIRED')
        print('Dashboard:', 'READY' if status['dashboard_ready'] else 'NOT READY')
        print('Playwright:', 'INSTALLED' if status['collector']['installed'] else 'MISSING')
        print('Chromium:', 'FOUND' if status['collector']['chromium'] else 'MISSING')
        if status['collector']['error']:
            print('Collector check failed:', status['collector']['error'])
        print('Public/account collection:', 'READY FOR ONLINE VERIFICATION' if status['collection_ready'] else 'SETUP REQUIRED')
        if not status['collection_ready']:
            print('Run setup.cmd in this project folder, then run check.cmd again.')
        print('No account connected and no order sent by this check.')
        print('Online source, account and execution checks remain separate.')
    return 0 if status['collection_ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
