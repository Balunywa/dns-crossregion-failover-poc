import struct

import unittest



from analyze import dns_decode, dns_name, packet_decode

from test_upstream import query, upstream





class DecodeTests(unittest.TestCase):

    def test_response_and_compression(self):

        response, _ = upstream.reply(query(), "192.0.2.20")

        decoded = dns_decode(response)

        self.assertEqual(decoded["name"], "unique.lab.failover.test")

        self.assertEqual(decoded["answers"], ["192.0.2.20"])

        self.assertTrue(decoded["response"])



    def test_servfail_wire_decode(self):

        response, _ = upstream.reply(query(), "192.0.2.10", "servfail")

        self.assertEqual(dns_decode(response)["rcode"], 2)



    def test_cyclic_pointer_is_explicit_error(self):

        with self.assertRaises(ValueError):

            dns_name(b"\xc0\x00", 0)



    def test_udp_ethernet(self):

        import socket

        dns = query()

        udp = struct.pack("!4H", 50000, 53, 8 + len(dns), 0) + dns

        ip = bytes([0x45, 0]) + struct.pack("!H", 20 + len(udp)) + bytes(5) + bytes([17]) + bytes(2) + socket.inet_aton("10.20.0.5") + socket.inet_aton("168.63.129.16") + udp

        ether = bytes(12) + b"\x08\x00" + ip

        decoded = packet_decode(123, 1, ether)

        self.assertEqual(decoded["destination"], "168.63.129.16")

        self.assertEqual(decoded["qtype"], 1)



    def test_unsupported_link_type_not_silent(self):

        with self.assertRaises(ValueError):

            packet_decode(123, 999, b"")





if __name__ == "__main__":

    unittest.main()

