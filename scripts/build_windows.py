"""Build only from source and installed packages; never copy a developer's data directory."""
from importlib import metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform != 'win32':
        raise SystemExit('Build the Windows package on Windows, or use the GitHub Windows workflow.')
    os.chdir(ROOT)
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'
    subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'], check=True)
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onedir',
        '--name', 'PoloCopyTrade', '--distpath', str(ROOT / 'dist'),
        '--icon', str(ROOT / 'frontend' / 'polo.ico'),
        '--workpath', str(ROOT / 'build'), '--specpath', str(ROOT / 'build'),
        '--paths', str(ROOT), '--collect-all', 'playwright',
        '--collect-all', 'greenlet',
        '--copy-metadata', 'playwright', '--copy-metadata', 'greenlet',
        '--add-data', str(ROOT / 'frontend') + os.pathsep + 'frontend',
        str(ROOT / 'polo.py'),
    ], check=True)
    app = ROOT / 'dist' / 'PoloCopyTrade'
    # Explicit public-document allowlist: no credentials, .env, data or databases.
    for source, target in (
        ('LICENSE', 'LICENSE'), ('docs/PORTABLE.md', 'START_HERE.md'),
        ('docs/ACCOUNT_GUIDE.md', 'ACCOUNT_GUIDE.md'),
        ('docs/DEMO_EXECUTION.md','DEMO_EXECUTION.md'),
        ('docs/REAL_EXECUTION.md','REAL_EXECUTION.md'),
    ):
        shutil.copyfile(ROOT / source, app / target)
    (app / 'Connect-Account.cmd').write_text(
        '@echo off\ncd /d "%~dp0"\nPoloCopyTrade.exe --connect\npause\n', encoding='ascii')
    (app / 'Check-Setup.cmd').write_text(
        '@echo off\ncd /d "%~dp0"\nPoloCopyTrade.exe --check\npause\n', encoding='ascii')
    (app / 'Open-Demo-Preview.cmd').write_text('@echo off\ncd /d "%~dp0"\nPoloCopyTrade.exe --demo --preview\npause\n',encoding='ascii')
    (app / 'Connect-Demo.cmd').write_text('@echo off\ncd /d "%~dp0"\nPoloCopyTrade.exe --demo\npause\n',encoding='ascii')
    (app / 'Open-Real-Workspace.cmd').write_text('@echo off\ncd /d "%~dp0"\nPoloCopyTrade.exe --real\nif errorlevel 1 pause\n',encoding='ascii')
    (app / 'Connect-Trading-Subaccount.cmd').write_text('@echo off\ncd /d "%~dp0"\nPoloCopyTrade.exe --connect-trading --no-browser\npause\n',encoding='ascii')
    licenses = app / 'THIRD_PARTY_LICENSES'
    licenses.mkdir(exist_ok=True)
    versions = {}
    for package in ('playwright', 'greenlet', 'pyinstaller'):
        dist = metadata.distribution(package)
        versions[package] = dist.version
        for index, item in enumerate(dist.files or []):
            if any(token in item.name.lower() for token in ('license', 'copying', 'notice')):
                source = Path(dist.locate_file(item))
                if source.is_file() and source.stat().st_size < 2_000_000:
                    target = licenses / (package + '-' + str(index) + '-' + item.name)
                    shutil.copyfile(source, target)
    (app / 'BUILD_INFO.json').write_text(
        json.dumps(dict(python=sys.version.split()[0], packages=versions), indent=2) + '\n')
    print('Built:', app)
    print('Run scripts/smoke_windows.py, then scripts/archive_windows.py before distribution.')


if __name__ == '__main__':
    main()
