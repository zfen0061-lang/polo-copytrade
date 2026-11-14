import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import polo
from backend.doctor import browser_files, browser_cache
from backend import paths
from scripts import archive_windows


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / 'playwright'
        manifest = self.package / 'driver/package/browsers.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps(dict(browsers=[
            dict(name='chromium', revision='123'),
            dict(name='chromium-headless-shell', revision='123'),
        ])))

    def tearDown(self):
        self.temp.cleanup()

    def binary(self, path):
        file = self.root / 'cache' / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'binary-placeholder')

    def test_matching_full_browser_and_shell_are_required(self):
        self.binary('chromium-123/chrome-win64/chrome.exe')
        self.assertFalse(browser_files(self.package, self.root / 'cache', 'win32'))
        self.binary('chromium_headless_shell-123/chrome-headless-shell-win64/chrome-headless-shell.exe')
        self.assertTrue(browser_files(self.package, self.root / 'cache', 'win32'))

    def test_another_browser_revision_does_not_satisfy_installed_playwright(self):
        self.binary('chromium-122/chrome-win64/chrome.exe')
        self.binary('chromium_headless_shell-122/chrome-headless-shell-win64/chrome-headless-shell.exe')
        self.assertFalse(browser_files(self.package, self.root / 'cache', 'win32'))

    def test_bundled_browser_uses_package_local_cache(self):
        with patch.dict(os.environ, {'PLAYWRIGHT_BROWSERS_PATH':'0'}):
            self.assertEqual(browser_cache(self.package), self.package / 'driver/package/.local-browsers')

    def test_frozen_assets_resolve_from_read_only_bundle(self):
        with patch.object(paths.sys, 'frozen', True, create=True), patch.object(paths.sys, '_MEIPASS', str(self.root / 'bundle'), create=True):
            self.assertEqual(paths.resource_root(), self.root / 'bundle')

    def test_frozen_runtime_data_is_outside_bundle_and_working_directory(self):
        with patch.object(paths.sys, 'frozen', True, create=True), patch.dict(os.environ, {'LOCALAPPDATA':str(self.root / 'user')}):
            self.assertEqual(paths.default_data_dir(), self.root / 'user/PoloCopyTrade')

    def test_launcher_opens_browser_without_connecting_account(self):
        with patch('sys.argv', ['PoloCopyTrade.exe', '--port', '8766']), patch('backend.server.main') as server, patch('backend.connect.main') as connect:
            self.assertEqual(polo.main(), 0)
        server.assert_called_once_with(['--port', '8766', '--open-browser'])
        connect.assert_not_called()

    def test_account_launcher_forwards_data_path_and_does_not_open_browser_when_disabled(self):
        with patch('sys.argv', ['PoloCopyTrade.exe', '--connect', '--no-browser', '--data', 'existing.sqlite3']), patch('backend.connect.main') as connect:
            polo.main()
        connect.assert_called_once_with(['--data', 'existing.sqlite3'])

    def app_folder(self):
        app = self.root / 'dist/PoloCopyTrade'
        app.mkdir(parents=True)
        (app / 'PoloCopyTrade.exe').write_bytes(b'build-placeholder')
        return app

    def test_runtime_database_aborts_distribution(self):
        app = self.app_folder()
        (app / 'data').mkdir()
        (app / 'data/studio.sqlite3').write_bytes(b'private-runtime-state')
        with patch.object(archive_windows, 'ROOT', self.root):
            with self.assertRaises(SystemExit):
                archive_windows.main()
        self.assertFalse((self.root / 'dist/PoloCopyTrade-Windows-x64.zip').exists())

    def test_archive_does_not_include_source_runtime_directory(self):
        self.app_folder()
        (self.root / 'data').mkdir()
        (self.root / 'data/source.sqlite3').write_bytes(b'private-source-state')
        with patch.object(archive_windows, 'ROOT', self.root):
            archive_windows.main()
        import zipfile
        with zipfile.ZipFile(self.root / 'dist/PoloCopyTrade-Windows-x64.zip') as archive:
            self.assertEqual(archive.namelist(), ['PoloCopyTrade/PoloCopyTrade.exe'])
        self.assertTrue((self.root / 'dist/PoloCopyTrade-Windows-x64.zip.sha256').is_file())


if __name__ == '__main__':
    unittest.main()
