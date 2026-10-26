import importlib.util

from pathlib import Path

import socket

import struct

import unittest



spec = importlib.util.spec_from_file_location("upstream", Path(__file__).parent / "guest" / "upstream.py")

upstream = importlib.util.module_from_spec(spec)

spec.loader.exec_module(upstream)





def query(name="unique.lab.failover.test", kind=1):

    return struct.pack("!6H", 123, 0x100, 1, 0, 0, 0) + b"".join(bytes([len(s)]) + s.encode() for s in name.split(".")) + b"\0" + struct.pack("!HH", kind, 1)





class UpstreamTests(unittest.TestCase):

    def test_fingerprint_and_ttl(self):

        response, detail = upstream.reply(query(), "192.0.2.10")

        self.assertEqual(response[-4:], socket.inet_aton("192.0.2.10"))

        self.assertEqual(detail["rcode"], 0)

        self.assertEqual(struct.unpack("!I", response[-10:-6])[0], 0)



    def test_servfail_has_no_answer(self):

        response, detail = upstream.reply(query(), "192.0.2.20", "servfail")

        self.assertEqual(response[3] & 15, 2)

        self.assertEqual(struct.unpack("!H", response[6:8])[0], 0)

        self.assertIsNone(detail["answer"])



    def test_aaaa_is_nodata(self):

        response, detail = upstream.reply(query(kind=28), "192.0.2.10")

        self.assertEqual(detail["rcode"], 0)

        self.assertEqual(struct.unpack("!H", response[6:8])[0], 0)



    def test_nxdomain(self):

        _, detail = upstream.reply(query("nx-control.lab.failover.test"), "192.0.2.10")

        self.assertEqual(detail["rcode"], 3)



    def test_other_zone_refused(self):

        _, detail = upstream.reply(query("example.org"), "192.0.2.10")

        self.assertEqual(detail["rcode"], 5)



    def test_malformed_is_explicit_error(self):

        with self.assertRaises(ValueError):

            upstream.reply(b"bad", "192.0.2.10")





if __name__ == "__main__":

    unittest.main()

