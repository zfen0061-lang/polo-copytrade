"""Archive the built app, keeping runtime data and credentials out of release files."""
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    app = ROOT / 'dist' / 'PoloCopyTrade'
    if not (app / 'PoloCopyTrade.exe').is_file():
        raise SystemExit('Build the Windows app first.')
    files = [p for p in app.rglob('*') if p.is_file()]
    for path in files:
        name = path.name.lower()
        parts = [part.lower() for part in path.relative_to(app).parts]
        if parts[0] == 'data' or name == '.env' or name.startswith('.env.') or '.sqlite' in name or name.endswith(('.pem', '.key', '.log')):
            raise SystemExit('Unexpected private/runtime file in distribution: ' + str(path.relative_to(app)))
    target = ROOT / 'dist' / 'PoloCopyTrade-Windows-x64.zip'
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, Path('PoloCopyTrade') / path.relative_to(app))
    hasher = hashlib.sha256()
    with target.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            hasher.update(chunk)
    digest = hasher.hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest + '  ' + target.name + '\n', encoding='ascii')
    print('Created:', target)
    print('SHA256:', digest)


if __name__ == '__main__':
    main()
