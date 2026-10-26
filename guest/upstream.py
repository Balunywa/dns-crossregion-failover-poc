"""Minimal lab-only authoritative DNS responder with regional answer fingerprints."""

import datetime

import ipaddress

import json

import os

from pathlib import Path

import socketserver

import struct

import threading



ZONE = "lab.failover.test"

STATE = Path(os.environ.get("DNS_LAB_STATE", "/var/lib/dns-lab"))

LOCK = threading.Lock()





def event(data):

    STATE.mkdir(parents=True, exist_ok=True)

    data["utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with LOCK, (STATE / "upstream.jsonl").open("a") as stream:

        stream.write(json.dumps(data) + "\n")





def reply(packet, answer, mode="healthy"):

    if len(packet) < 12:

        raise ValueError("DNS header is incomplete")

    ident, flags, count, _, _, _ = struct.unpack("!6H", packet[:12])

    if count != 1 or flags & 0x8000:

        raise ValueError("Expected one question in a DNS query")

    offset, labels = 12, []

    while True:

        if offset >= len(packet):

            raise ValueError("Truncated DNS name")

        length = packet[offset]

        offset += 1

        if length == 0:

            break

        if length > 63 or offset + length > len(packet):

            raise ValueError("Invalid DNS label")

        labels.append(packet[offset:offset + length].decode("ascii"))

        offset += length

    if offset + 4 > len(packet):

        raise ValueError("Truncated DNS question")

    qtype, qclass = struct.unpack("!HH", packet[offset:offset + 4])

    question = packet[12:offset + 4]

    name = ".".join(labels).lower()

    rcode = 2 if mode == "servfail" else 0

    if mode != "servfail" and not (name == ZONE or name.endswith("." + ZONE)):

        rcode = 5

    if mode != "servfail" and name.startswith("nx-"):

        rcode = 3

    records = b""

    if rcode == 0 and qtype == 1 and qclass == 1:

        records = b"\xc0\x0c" + struct.pack("!HHIH", 1, 1, 0, 4) + ipaddress.ip_address(answer).packed

    header = struct.pack("!6H", ident, 0x8480 | (flags & 0x0100) | rcode, 1, int(bool(records)), 0, 0)

    return header + question + records, {"name": name, "qtype": qtype, "rcode": rcode, "answer": answer if records else None}





def process(packet, peer, protocol):

    mode_file = STATE / "mode"

    mode = mode_file.read_text().strip() if mode_file.exists() else "healthy"

    response, detail = reply(packet, os.environ["DNS_LAB_ANSWER"], mode)

    event(dict(detail, source=peer[0], protocol=protocol, mode=mode))

    return response





class UDP(socketserver.BaseRequestHandler):

    def handle(self):

        packet, sock = self.request

        try:

            sock.sendto(process(packet, self.client_address, "UDP"), self.client_address)

        except (ValueError, UnicodeError, OSError) as exc:

            event({"error": str(exc), "source": self.client_address[0]})





def receive_exact(sock, length):

    data = b""

    while len(data) < length:

        block = sock.recv(length - len(data))

        if not block:

            raise ValueError("Incomplete TCP DNS message")

        data += block

    return data





class TCP(socketserver.BaseRequestHandler):

    def handle(self):

        self.request.settimeout(10)

        try:

            length = struct.unpack("!H", receive_exact(self.request, 2))[0]

            response = process(receive_exact(self.request, length), self.client_address, "TCP")

            self.request.sendall(struct.pack("!H", len(response)) + response)

        except (ValueError, UnicodeError, OSError) as exc:

            event({"error": str(exc), "source": self.client_address[0]})





if __name__ == "__main__":

    address = (os.environ["DNS_LAB_BIND"], 53)

    udp = socketserver.ThreadingUDPServer(address, UDP)

    tcp = socketserver.ThreadingTCPServer(address, TCP)

    threading.Thread(target=tcp.serve_forever, daemon=True).start()

    event({"event": "started", "bind": address[0], "answer": os.environ["DNS_LAB_ANSWER"]})

    udp.serve_forever()

