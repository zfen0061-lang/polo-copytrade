import hashlib
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from scripts.install_desktop import extract_app, verify_archive


class DesktopInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_complete_app_folder_is_extracted_without_extra_root_level(self):
        archive = self.root / 'app.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('PoloCopyTrade/PoloCopyTrade.exe', b'placeholder')
            z.writestr('PoloCopyTrade/_internal/frontend/index.html', '<title>Polo</title>')
        extract_app(archive, self.root / 'install')
        self.assertEqual((self.root / 'install/PoloCopyTrade.exe').read_bytes(), b'placeholder')
        self.assertTrue((self.root / 'install/_internal/frontend/index.html').is_file())

    def test_archive_cannot_write_outside_selected_app_directory(self):
        for name in ('../escape.exe', 'PoloCopyTrade/../../escape.exe', 'C:/escape.exe', '/escape.exe'):
            with self.subTest(name=name):
                archive = self.root / 'bad.zip'
                with zipfile.ZipFile(archive, 'w') as z:
                    z.writestr(name, b'bad')
                with self.assertRaises(ValueError):
                    extract_app(archive, self.root / 'install')
        self.assertFalse((self.root / 'escape.exe').exists())

    def test_archive_symlinks_are_rejected(self):
        archive = self.root / 'link.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            link = zipfile.ZipInfo('PoloCopyTrade/link')
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(link, '../elsewhere')
        with self.assertRaises(ValueError):
            extract_app(archive, self.root / 'install')

    def test_modified_download_does_not_pass_release_checksum(self):
        archive, checksum = self.root / 'app.zip', self.root / 'app.sha256'
        archive.write_bytes(b'original')
        checksum.write_text(hashlib.sha256(b'original').hexdigest() + '  app.zip\n')
        verify_archive(archive, checksum)
        archive.write_bytes(b'modified')
        with self.assertRaises(ValueError):
            verify_archive(archive, checksum)

    def test_invalid_checksum_response_is_rejected(self):
        checksum = self.root / 'app.sha256'
        checksum.write_text('<html>download failed</html>')
        with self.assertRaises(ValueError):
            verify_archive(self.root / 'missing.zip', checksum)


if __name__ == '__main__':
    unittest.main()
