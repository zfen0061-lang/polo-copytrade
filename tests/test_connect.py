import os
import unittest
from unittest.mock import patch

from backend.connect import main


class ConnectTests(unittest.TestCase):
    def test_production_read_only_launcher_forces_environment_and_server_guard(self):
        with patch.dict(os.environ, {}, clear=True), patch('backend.connect.getpass.getpass', side_effect=['fake-key', 'fake-secret']), patch('builtins.input') as choose, patch('builtins.print'), patch('backend.server.main') as server:
            main(['--production-read-only', '--no-runner'])
            choose.assert_not_called()
            self.assertEqual(os.environ['POLO_BINANCE_ENV'], 'production')
            self.assertIn('--read-only-account', server.call_args.args[0])
            self.assertIn('--no-runner', server.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
