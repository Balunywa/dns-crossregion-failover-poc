"""Exercise native libc -> systemd-resolved, never implementing DNS retries here."""

import datetime

import json

import os

from pathlib import Path

import signal

import socket

import subprocess

import time

import uuid



phase = os.environ["DNS_LAB_PHASE"]

primary = "10.10.2.4" if phase == "fast-servfail-control" else "168.63.129.16"

root = Path("/var/lib/dns-lab") / phase

root.mkdir(parents=True, exist_ok=True)

(root / "queries.jsonl").write_text("")

interface = subprocess.check_output(["sh", "-c", "ip -4 route show default | awk 'NR==1 {print $5}'"], text=True).strip()





def run(*args):

    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True).stdout





def record(data):

    data["utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    with (root / "queries.jsonl").open("a") as stream:

        stream.write(json.dumps(data) + "\n")





run("systemctl", "restart", "systemd-resolved")

run("resolvectl", "dns", interface, primary, "10.30.0.4")

run("resolvectl", "domain", interface, "~.")

run("resolvectl", "flush-caches")

(root / "configuration.txt").write_text(

    run("resolvectl", "status") + "\n" + Path("/etc/resolv.conf").read_text() + "\n" +

    Path("/etc/os-release").read_text() + "\n" + run("resolvectl", "--version") + "\n" + run("uname", "-a"))

capture = subprocess.Popen(["tcpdump", "--immediate-mode", "-U", "-i", "any", "-s", "0", "-w", str(root / "dns.pcap"), "port", "53"],

                           stdout=subprocess.DEVNULL, stderr=(root / "capture.log").open("w"))

time.sleep(1)

if capture.poll() is not None:

    raise RuntimeError("tcpdump did not start")

blocked = False





def firewall(action):

    for protocol in ("udp", "tcp"):

        run("iptables", action, "OUTPUT", "-d", "168.63.129.16", "-p", protocol, "--dport", "53",

            "-m", "comment", "--comment", "dns-lab-primary-timeout", "-j", "DROP")





def query(index, stage):

    name = f"{phase}-{stage}-{index}-{uuid.uuid4().hex[:10]}.lab.failover.test"

    start_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()

    start = time.perf_counter()

    try:

        records = socket.getaddrinfo(name, None, socket.AF_INET, socket.SOCK_STREAM)

        answers = sorted({item[4][0] for item in records})

        result = {"success": True, "answers": answers}

    except socket.gaierror as exc:

        result = {"success": False, "answers": [], "error": str(exc), "errno": exc.errno}

    record(dict(result, kind="native", name=name, phase=phase, stage=stage, index=index,

                primary=primary, startedUtc=start_utc, elapsedMs=round((time.perf_counter() - start) * 1000, 3)))

    time.sleep(0.5)





try:

    if phase == "primary-timeout":

        for i in range(3):

            query(i, "before")

        # Automatic guest-side rollback even if the orchestrator is interrupted.

        rollback = "sleep 480; " + "; ".join(

            f"iptables -D OUTPUT -d 168.63.129.16 -p {p} --dport 53 -m comment --comment dns-lab-primary-timeout -j DROP"

            for p in ("udp", "tcp"))

        subprocess.Popen(["sh", "-c", rollback], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,

                         start_new_session=True)

        firewall("-I")

        blocked = True

        record({"kind": "fault-applied", "phase": phase, "firewall": run("iptables", "-L", "OUTPUT", "-n", "-v")})

    for i in range(15):

        query(i, "fault" if phase != "baseline" and phase != "recovery" else "healthy")

    # Explicit probes are diagnostics only and are deliberately AFTER the native stream.

    servers = [primary, "10.30.0.4"]

    if phase == "no-east-peering":

        servers.append("10.10.0.4")

    for server in servers:

        diagnostic = subprocess.run(["dig", "@" + server, f"diag-{uuid.uuid4().hex[:10]}.lab.failover.test", "A",

                                     "+tries=1", "+time=12"], capture_output=True, text=True)

        record({"kind": "direct", "server": server, "exitCode": diagnostic.returncode, "output": diagnostic.stdout + diagnostic.stderr})

finally:

    if phase == "fast-servfail-control":

        run("resolvectl", "dns", interface, "168.63.129.16", "10.30.0.4")

        run("resolvectl", "flush-caches")

    if blocked:

        firewall("-D")

        record({"kind": "fault-restored", "phase": phase, "firewall": run("iptables", "-L", "OUTPUT", "-n", "-v")})

        for i in range(3):

            query(i, "after")

    time.sleep(2)

    capture.send_signal(signal.SIGINT)

    capture.wait(timeout=15)

    if capture.returncode != 0:

        raise RuntimeError(f"tcpdump failed: {capture.returncode}")

(root / "packets.txt").write_text(run("tcpdump", "-nn", "-tttt", "-r", str(root / "dns.pcap")))

print(json.dumps({"phase": phase, "evidence": str(root), "complete": True}))

