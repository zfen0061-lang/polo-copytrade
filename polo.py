"""Desktop/portable entry point. Opening the app never starts account execution."""
import argparse
import json
from pathlib import Path
import sys

from backend.paths import configure_bundled_browser, resource_root


def smoke_test():
    from backend.doctor import inspect_setup
    state = inspect_setup()
    if not state['collection_ready']:
        raise SystemExit('Packaged collector dependencies are incomplete: ' + json.dumps(state))
    for name in ('index.html', 'app.js', 'live-ui.js', 'style.css', 'polo-logo.png','testnet.html','demo-ui.js','demo.css','real.html','real-ui.js'):
        if not (resource_root() / 'frontend' / name).is_file():
            raise SystemExit('Missing packaged frontend asset: ' + name)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content('<title>Polo package smoke test</title><p>Local page</p>')
            if page.title() != 'Polo package smoke test':
                raise SystemExit('Packaged browser failed its local-page check')
        finally:
            browser.close()
    print('Packaged assets and bundled browser verified. No account connection or order.')


def main():
    configure_bundled_browser()
    parser = argparse.ArgumentParser(description='Polo CopyTrade portable launcher')
    parser.add_argument('--connect', action='store_true', help='Enter credentials locally before opening')
    parser.add_argument('--demo',action='store_true',help='Separate Futures Demo workspace with local credential input')
    parser.add_argument('--real',action='store_true',help='Open a disarmed production workspace')
    parser.add_argument('--connect-trading',action='store_true',help='Enter and remember the dedicated trading sub-account keys locally; no orders')
    parser.add_argument('--real-server',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--demo-verify',action='store_true',help='Bounded Futures Demo stop check only')
    parser.add_argument('--check', action='store_true', help='Check local dependencies and exit')
    parser.add_argument('--smoke-test', action='store_true', help='Local packaged-browser verification')
    parser.add_argument('--no-browser', action='store_true', help='Do not open the system browser')
    args, rest = parser.parse_known_args()
    if args.connect_trading:
        if any((args.real,args.real_server,args.demo,args.demo_verify,args.connect,args.check,args.smoke_test)):
            parser.error('Choose only the dedicated trading connection')
        from backend.trading_connect import main as connect_trading
        return connect_trading([*rest,*(['--no-browser'] if args.no_browser else [])])
    if args.real_server:
        if args.real or args.demo or args.connect or args.check or args.smoke_test or args.demo_verify:parser.error('Choose one workspace')
        from backend.server import main as server
        return server(rest)
    if args.real:
        if args.demo or args.connect or args.check or args.smoke_test or args.demo_verify:parser.error('Choose one workspace')
        from backend.real_connect import main as real
        return real([*rest,*(['--no-browser'] if args.no_browser else [])])
    if args.demo_verify:
        if args.demo or args.connect or args.check or args.smoke_test:parser.error('Choose only Demo verification')
        from backend.demo_verify import main as verify
        return verify(rest)
    if args.demo and (args.connect or args.check or args.smoke_test):parser.error('Choose the separate Demo workspace without other execution modes')
    if args.demo:
        from backend.demo_connect import main as demo
        return demo([*rest,*(['--no-browser'] if args.no_browser else [])])
    if args.check:
        from backend.doctor import main as check
        return check(rest)
    if args.smoke_test:
        smoke_test()
        return 0
    server_args = list(rest)
    if not args.no_browser:
        server_args.append('--open-browser')
    if args.connect:
        from backend.connect import main as connect
        connect(server_args)
    else:
        from backend.server import main as server
        server(server_args)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        pass
