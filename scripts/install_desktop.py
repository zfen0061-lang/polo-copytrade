"""Install the published portable app and create its Windows desktop shortcut.

Run by the user outside the restricted agent environment. No account or trading requests.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

VERSION = 'v0.3.0-preview'
ASSET = 'PoloCopyTrade-Windows-x64.zip'
BASE = 'https://github.com/zfen0061-lang/polo-copytrade/releases/download/' + VERSION + '/'
ROOT = Path(__file__).resolve().parents[1]


def desktop_directory():
    result = subprocess.run([
        'powershell.exe', '-NoProfile', '-Command',
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();[Environment]::GetFolderPath('Desktop')",
    ], check=True, capture_output=True, text=True, encoding='utf-8', timeout=15)
    value = result.stdout.strip()
    if not value:
        raise RuntimeError('Windows did not return a desktop directory.')
    return Path(value)


def extract_app(archive, target):
    target = target.resolve()
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            relative = PurePosixPath(item.filename.replace('\\', '/'))
            if (relative.is_absolute() or '..' in relative.parts
                    or any(':' in part for part in relative.parts)
                    or not relative.parts or relative.parts[0] != 'PoloCopyTrade'
                    or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('Invalid archive path: ' + item.filename)
            destination = target.joinpath(*relative.parts[1:]).resolve()
            if not destination.is_relative_to(target):
                raise ValueError('Archive path leaves the install directory.')
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(item) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
    if not (target / 'PoloCopyTrade.exe').is_file():
        raise ValueError('The archive does not contain the expected app executable.')


def download(url, target):
    if not url.startswith(BASE):
        raise ValueError('Only this project release can be downloaded.')
    request = urllib.request.Request(url, headers={'User-Agent':'PoloCopyTrade-Desktop-Setup'})
    with urllib.request.urlopen(request, timeout=30) as response, target.open('wb') as output:
        total = int(response.headers.get('Content-Length') or 0)
        received, last = 0, 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            received += len(chunk)
            if received - last >= 20 * 1024 * 1024:
                print('Downloaded', received // (1024 * 1024), 'MB',
                      ('/ ' + str(total // (1024 * 1024)) + ' MB') if total else '', flush=True)
                last = received


def verify_archive(archive, checksum):
    parts = checksum.read_text(encoding='ascii').split()
    if not parts or not re.fullmatch('[0-9a-fA-F]{64}', parts[0]):
        raise ValueError('Invalid release checksum file.')
    expected = parts[0].lower()
    hasher = hashlib.sha256()
    with archive.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            hasher.update(chunk)
    if hasher.hexdigest() != expected:
        raise ValueError('Download checksum did not match. Installation stopped.')


def write_launcher(app):
    # PowerShell receives paths through an environment variable, never interpolated as code.
    # An existing Polo instance is reused. An unrelated service is never presented as Polo.
    command = (
        "$u='http://127.0.0.1:8765';$r=$null;"
        "try{$r=Invoke-WebRequest ($u+'/api/live/state') -UseBasicParsing -TimeoutSec 3}catch{};"
        "if($r){if($r.Headers['Server'] -like 'PoloCopyTrade/*'){Start-Process $u}else{"
        "$w=New-Object -ComObject WScript.Shell;"
        "$null=$w.Popup('Port 8765 is occupied by another application.',0,'Polo CopyTrade',16)}}"
        "else{$p=Start-Process -FilePath (Join-Path $env:POLO_APP_DIR 'PoloCopyTrade.exe') "
        "-WorkingDirectory $env:POLO_APP_DIR -WindowStyle Hidden -PassThru;"
        "$p.Id|Set-Content -LiteralPath (Join-Path $env:POLO_APP_DIR 'service.pid')}"
    )
    text = '@echo off\nset "POLO_APP_DIR=%~dp0"\npowershell.exe -NoProfile -Command "' + command + '"\n'
    (app / 'Open-Polo.cmd').write_bytes(text.replace('\n', '\r\n').encode('ascii'))
    close_command = (
        "$f=Join-Path $env:POLO_APP_DIR 'service.pid';"
        "if(Test-Path -LiteralPath $f){$pidText=Get-Content -LiteralPath $f;"
        "$process=Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue;"
        "if($process -and $process.Path -eq (Join-Path $env:POLO_APP_DIR 'PoloCopyTrade.exe')){"
        "Stop-Process -Id $process.Id}}"
    )
    close_text = ('@echo off\nset "POLO_APP_DIR=%~dp0"\n'
                  'echo Stop account following in the webpage first. Closing the local service does not close exchange positions.\n'
                  'powershell.exe -NoProfile -Command "' + close_command + '"\npause\n')
    (app / 'Close-Polo.cmd').write_bytes(close_text.replace('\n', '\r\n').encode('ascii'))


def create_shortcut(app, desktop):
    desktop.mkdir(parents=True, exist_ok=True)
    shortcut = desktop / 'Polo CopyTrade.lnk'
    env = dict(os.environ, POLO_APP_DIR=str(app), POLO_SHORTCUT=str(shortcut))
    command = (
        "$w=New-Object -ComObject WScript.Shell;"
        "$s=$w.CreateShortcut($env:POLO_SHORTCUT);"
        "$s.TargetPath=Join-Path $env:POLO_APP_DIR 'Open-Polo.cmd';"
        "$s.WorkingDirectory=$env:POLO_APP_DIR;"
        "$s.IconLocation=(Join-Path $env:POLO_APP_DIR 'polo.ico')+',0';"
        "$s.WindowStyle=7;$s.Description='Polo CopyTrade - local app';$s.Save()"
    )
    subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                   check=True, env=env, timeout=15)
    if not shortcut.is_file():
        raise RuntimeError('The desktop shortcut was not created.')
    return shortcut


def main():
    parser = argparse.ArgumentParser(description='Install portable Polo and its desktop shortcut')
    parser.add_argument('--plan', action='store_true', help='Show paths only; no download or writes')
    parser.add_argument('--no-open', action='store_true', help='Create shortcut without opening it')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise SystemExit('This installer supports Windows x64 only.')
    app_base = Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData/Local') / 'Programs/PoloCopyTrade'
    app = app_base / VERSION
    desktop = desktop_directory()
    if args.plan:
        print(json.dumps(dict(app=str(app), desktop=str(desktop), release=BASE+ASSET,
                              shortcut=str(desktop/'Polo CopyTrade.lnk')), ensure_ascii=True))
        return
    app_base.mkdir(parents=True, exist_ok=True)
    if (app / 'PoloCopyTrade.exe').is_file() and not (app / '_internal/frontend/index.html').is_file():
        raise RuntimeError('The existing app folder is incomplete. Keep all extracted subfolders: ' + str(app))
    if not (app / 'PoloCopyTrade.exe').is_file():
        if app.exists():
            raise RuntimeError('An incomplete installation already exists at ' + str(app))
        print('Downloading the published Windows app (about 387 MB). No keys are needed.', flush=True)
        # Staging and its automatic cleanup stay inside the explicit install parent.
        with tempfile.TemporaryDirectory(prefix='.setup-', dir=app_base) as folder:
            stage = Path(folder).resolve()
            if stage.parent != app_base.resolve():
                raise RuntimeError('Unexpected staging directory.')
            archive, checksum = stage / ASSET, stage / (ASSET + '.sha256')
            download(BASE+ASSET+'.sha256', checksum)
            download(BASE+ASSET, archive)
            verify_archive(archive, checksum)
            print('Checksum verified. Extracting app...', flush=True)
            extracted = stage / 'app'
            extract_app(archive, extracted)
            extracted.rename(app)
    shutil.copyfile(ROOT / 'frontend/polo.ico', app / 'polo.ico')
    write_launcher(app)
    shortcut = create_shortcut(app, desktop)
    print('Desktop shortcut created:', shortcut, flush=True)
    print('The app is installed in:', app, flush=True)
    print('Opening the app does not connect an account or start trading.', flush=True)
    if not args.no_open:
        os.startfile(shortcut)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Desktop setup stopped:', error, file=sys.stderr)
        raise SystemExit(1)
