import socket
import sys
import unittest

from backend.server import LocalHTTPServer


class ServerSocketTests(unittest.TestCase):
    def test_second_instance_cannot_take_over_the_same_address(self):
        with LocalHTTPServer(('127.0.0.1',0),lambda *args:None) as first:
            with self.assertRaises(OSError):
                with LocalHTTPServer(first.server_address,lambda *args:None):
                    self.fail('A second instance occupied the active address')
            # Older Windows builds used SO_REUSEADDR, which must also be rejected.
            with socket.socket() as legacy:
                legacy.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                with self.assertRaises(OSError):
                    legacy.bind(first.server_address)
            if sys.platform=='win32':
                self.assertEqual(first.socket.getsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE),1)


if __name__=='__main__':
    unittest.main()
