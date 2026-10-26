"""Decode DNS wire evidence without external dependencies; summarize native calls."""

import argparse

from collections import Counter, defaultdict

import datetime as dt

import json

import math

from pathlib import Path

import socket

import struct





def dns_name(data, offset):

    parts, end, seen = [], None, set()

    while True:

        if offset in seen or offset >= len(data):

            raise ValueError("Invalid DNS name pointer")

        seen.add(offset)

        size = data[offset]

        if size & 0xC0 == 0xC0:

            if offset + 1 >= len(data):

                raise ValueError("Truncated DNS pointer")

            if end is None:

                end = offset + 2

            offset = ((size & 63) << 8) | data[offset + 1]

            continue

        offset += 1

        if not size:

            return ".".join(parts).lower(), end or offset

        if size > 63 or offset + size > len(data):

            raise ValueError("Invalid DNS label")

        parts.append(data[offset:offset + size].decode("ascii"))

        offset += size





def dns_decode(data):

    if len(data) < 12:

        raise ValueError("Incomplete DNS header")

    ident, flags, qd, an, _, _ = struct.unpack("!6H", data[:12])

    if qd != 1:

        raise ValueError(f"Unsupported DNS question count: {qd}")

    name, offset = dns_name(data, 12)

    qtype, _ = struct.unpack("!HH", data[offset:offset + 4])

    offset += 4

    answers = []

    for _ in range(an):

        _, offset = dns_name(data, offset)

        kind, _, _, length = struct.unpack("!HHIH", data[offset:offset + 10])

        offset += 10

        if offset + length > len(data):

            raise ValueError("Truncated DNS answer")

        if kind == 1 and length == 4:

            answers.append(socket.inet_ntoa(data[offset:offset + length]))

        offset += length

    return {"id": ident, "response": bool(flags & 0x8000), "rcode": flags & 15,

            "name": name, "qtype": qtype, "answers": answers}





def frames(path):

    with path.open("rb") as stream:

        magic = stream.read(4)

        stream.seek(0)

        if magic == b"\x0a\x0d\x0d\x0a":

            endian, interfaces = "<", []

            while True:

                header = stream.read(8)

                if not header:

                    break

                if len(header) != 8:

                    raise ValueError("Truncated pcapng block")

                if header[:4] == b"\x0a\x0d\x0d\x0a":

                    bom = stream.read(4)

                    endian = "<" if bom == b"\x4d\x3c\x2b\x1a" else ">"

                    size = struct.unpack(endian + "I", header[4:8])[0]

                    body = bom + stream.read(size - 12)

                    interfaces = []

                    continue

                kind, size = struct.unpack(endian + "II", header)

                if size < 12:

                    raise ValueError("Invalid pcapng block length")

                body = stream.read(size - 8)

                if len(body) != size - 8:

                    raise ValueError("Incomplete pcapng block")

                if kind == 1:

                    link = struct.unpack(endian + "H", body[:2])[0]

                    resolution, pos = 1e-6, 8

                    while pos + 4 < len(body) - 4:

                        code, length = struct.unpack(endian + "HH", body[pos:pos + 4])

                        pos += 4

                        if code == 9 and length:

                            exponent = body[pos]

                            resolution = 2 ** -(exponent & 127) if exponent & 128 else 10 ** -exponent

                        pos += (length + 3) & ~3

                    interfaces.append((link, resolution))

                elif kind == 6:

                    interface, high, low, captured, _ = struct.unpack(endian + "5I", body[:20])

                    link, resolution = interfaces[interface]

                    yield ((high << 32) | low) * resolution, link, body[20:20 + captured]

        else:

            header = stream.read(24)

            endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"

            resolution = 1e-9 if magic in (b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d") else 1e-6

            link = struct.unpack(endian + "I", header[20:24])[0]

            while True:

                header = stream.read(16)

                if not header:

                    break

                seconds, fraction, captured, _ = struct.unpack(endian + "4I", header)

                yield seconds + fraction * resolution, link, stream.read(captured)





def packet_decode(timestamp, link, data):

    if link == 1:

        protocol = struct.unpack("!H", data[12:14])[0]

        offset = 14

        if protocol == 0x8100:

            protocol = struct.unpack("!H", data[16:18])[0]

            offset = 18

    elif link == 113:

        protocol, offset = struct.unpack("!H", data[14:16])[0], 16

    elif link == 276:

        protocol, offset = struct.unpack("!H", data[:2])[0], 20

    elif link == 101:

        protocol, offset = 0x800, 0

    else:

        raise ValueError(f"Unsupported capture link type {link}")

    if protocol != 0x800:

        return None

    ip = data[offset:]

    if len(ip) < 20:

        raise ValueError("Truncated IPv4 packet")

    ihl = (ip[0] & 15) * 4

    source, destination = socket.inet_ntoa(ip[12:16]), socket.inet_ntoa(ip[16:20])

    transport = ip[ihl:]

    if ip[9] not in (6, 17):

        return None

    sport, dport = struct.unpack("!HH", transport[:4])

    if sport != 53 and dport != 53:

        return None

    if ip[9] == 17:

        payload = transport[8:]

    else:

        offset = ((transport[12] >> 4) & 15) * 4

        payload = transport[offset:]

        if len(payload) < 2:

            return None

        length = struct.unpack("!H", payload[:2])[0]

        if len(payload) < length + 2:

            raise ValueError("Segmented TCP DNS is not reassembled")

        payload = payload[2:length + 2]

    return dict(dns_decode(payload), timestamp=timestamp,

                utc=dt.datetime.fromtimestamp(timestamp, dt.timezone.utc).isoformat(),

                source=source, destination=destination, sourcePort=sport, destinationPort=dport,

                protocol="UDP" if ip[9] == 17 else "TCP")





def read_capture(path):

    packets, errors = [], []

    for timestamp, link, raw in frames(path):

        try:

            packet = packet_decode(timestamp, link, raw)

            if packet:

                packets.append(packet)

        except (ValueError, struct.error, UnicodeError, IndexError) as exc:

            errors.append({"timestamp": timestamp, "error": str(exc)})

    return packets, errors





def percentile(values, fraction):

    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None





def analyze(folder):

    rows = []

    for query_file in sorted((folder / "extracted").glob("*/queries.jsonl")):

        client_phase = query_file.parent.name

        queries = [json.loads(line) for line in query_file.read_text(encoding="utf-8-sig").splitlines() if line.strip()]

        captures = list(query_file.parent.glob("*.pcap")) + list(query_file.parent.glob("*.pcapng"))

        if len(captures) != 1:

            raise ValueError(f"Expected one capture in {query_file.parent}")

        packets, errors = read_capture(captures[0])

        (query_file.parent / "decoded-dns.jsonl").write_text("".join(json.dumps(p) + "\n" for p in packets), encoding="utf-8")

        (query_file.parent / "decode-errors.json").write_text(json.dumps(errors, indent=2), encoding="utf-8")

        by_name = defaultdict(list)

        for packet in packets:

            by_name[packet["name"]].append(packet)

        native = [q for q in queries if q["kind"] == "native"]

        selected = [q for q in native if q["stage"] in ("fault", "healthy")]

        primary_address = selected[0].get("primary", "168.63.129.16") if selected else "168.63.129.16"

        answers = Counter(a for q in selected for a in q.get("answers", []))

        latencies = [q["elapsedMs"] for q in selected]

        qnames = {q["name"].lower() for q in selected}

        wire = [p for p in packets if p["name"] in qnames and p["qtype"] == 1]

        sends = [p for p in wire if not p["response"] and p["destination"] in (primary_address, "10.30.0.4")]

        west = [q for q in selected if "192.0.2.20" in q.get("answers", [])]

        for q in selected:

            qwire = sorted(by_name[q["name"].lower()], key=lambda p: p["timestamp"])

            primary = [p for p in qwire if not p["response"] and p["destination"] == primary_address and p["qtype"] == 1]

            secondary = [p for p in qwire if not p["response"] and p["destination"] == "10.30.0.4" and p["qtype"] == 1]

            start = dt.datetime.fromisoformat(q["startedUtc"].replace("Z", "+00:00")).timestamp()

            failures = [p for p in qwire if p["response"] and p["source"] == primary_address and p["qtype"] == 1 and p["rcode"] == 2]

            west_answers = [p for p in qwire if p["response"] and p["source"] == "10.30.0.4" and "192.0.2.20" in p["answers"]]

            q["wirePrimaryRequests"] = len(primary)

            q["wireWestRequests"] = len(secondary)

            q["wirePrimaryToWestMs"] = round((secondary[0]["timestamp"] - primary[0]["timestamp"]) * 1000, 3) if primary and secondary else None

            q["nativeStartToWestRequestMs"] = round((secondary[0]["timestamp"] - start) * 1000, 3) if secondary else None

            q["nativeStartToWestAnswerMs"] = round((west_answers[0]["timestamp"] - start) * 1000, 3) if west_answers else None

            q["nativeStartToPrimaryServfailMs"] = round((failures[0]["timestamp"] - start) * 1000, 3) if failures else None

            q["servfailBeforeWestRequest"] = bool(failures and secondary and failures[0]["timestamp"] <= secondary[0]["timestamp"])

        applied = [q for q in queries if q["kind"] == "fault-applied"]

        fault_to_first_west = None

        if applied and west:

            fault_time = dt.datetime.fromisoformat(applied[0]["utc"].replace("Z", "+00:00")).timestamp()

            west_time = dt.datetime.fromisoformat(west[0]["utc"].replace("Z", "+00:00")).timestamp()

            fault_to_first_west = round((west_time - fault_time) * 1000, 3)

        row = {

            "clientPhase": client_phase, "phase": selected[0]["phase"] if selected else None,

            "primaryAddress": primary_address,

            "calls": len(selected), "successes": sum(q["success"] for q in selected),

            "failures": sum(not q["success"] for q in selected), "answers": dict(answers),

            "latencyP50Ms": percentile(latencies, .5), "latencyP95Ms": percentile(latencies, .95),

            "latencyMaxMs": max(latencies) if latencies else None,

            "firstWestCallIndex": west[0]["index"] if west else None,

            "firstWestCallElapsedMs": west[0]["elapsedMs"] if west else None,

            "guestFaultToFirstWestCompletionMs": fault_to_first_west,

            "callsWithServfailBeforeWestRequest": sum(q["servfailBeforeWestRequest"] for q in selected),

            "primaryWireRequests": sum(p["destination"] == primary_address for p in sends),

            "westWireRequests": sum(p["destination"] == "10.30.0.4" for p in sends),

            "primaryServfailResponses": sum(p["response"] and p["source"] == primary_address and p["rcode"] == 2 for p in wire),

            "wireRcodes": dict(Counter(str(p["rcode"]) for p in wire if p["response"])),

            "decodeErrors": len(errors),

            "nativeDetails": selected,

            "directDiagnostics": [q for q in queries if q["kind"] == "direct"],

        }

        rows.append(row)

    summary = {"measurement": "Native client API elapsed time; DNS wire sends/replies are separately decoded. No application retries.",

               "captureCaveat": "Wire counts include any capture duplicates; blocked packets may not reach NIC capture. TCP segments are not reassembled; decode errors are explicit.",

               "results": rows}

    (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("| Client / phase | Calls | Failures | East / West | p50 ms | p95 ms | First West call ms | Primary SERVFAIL |")

    print("|---|---:|---:|---|---:|---:|---:|---:|")

    for row in rows:

        a = row["answers"]

        print(f"| {row['clientPhase']} | {row['calls']} | {row['failures']} | {a.get('192.0.2.10', 0)} / {a.get('192.0.2.20', 0)} | {row['latencyP50Ms']:.1f} | {row['latencyP95Ms']:.1f} | {row['firstWestCallElapsedMs']} | {row['primaryServfailResponses']} |")

    return summary





if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("evidence", type=Path)

    analyze(parser.parse_args().evidence)

