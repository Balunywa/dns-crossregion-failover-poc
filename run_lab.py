"""Deploy-independent Azure Run Command orchestration and evidence collection."""

import argparse

import base64

from concurrent.futures import ThreadPoolExecutor

import datetime as dt

import json

import os

from pathlib import Path

import shutil

import subprocess

import tempfile

import time

import zipfile

import tarfile



ROOT = Path(__file__).resolve().parent

AZ = shutil.which("az")

RG = "rg-dns-crossregion-failover-poc"

CLIENTS = ("dnspoc-win", "dnspoc-ubuntu")

SUBSCRIPTION = None

RUN = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

EVIDENCE = ROOT / "evidence" / RUN

STORAGE = None

SAS = None





def az(*args):

    if AZ is None:

        raise RuntimeError("Azure CLI is not installed or is not on PATH")

    scope = ["--subscription", SUBSCRIPTION] if SUBSCRIPTION else []

    completed = subprocess.run([AZ, *args, *scope, "--only-show-errors", "-o", "json"],

                               capture_output=True, text=True, encoding="utf-8")

    if completed.returncode:

        # Do not print command arguments: they may contain short-lived upload credentials.

        raise RuntimeError(f"az {' '.join(args[:2])} failed: {completed.stderr}")

    return json.loads(completed.stdout) if completed.stdout.strip() else None





def configure_context(subscription, resource_group):

    global SUBSCRIPTION, RG

    SUBSCRIPTION = subscription

    account = az("account", "show")

    if not account or not account.get("id"):

        raise RuntimeError("Azure CLI did not return a subscription; run az login first")

    SUBSCRIPTION = account["id"]

    RG = resource_group

    return account





def save(name, data):

    EVIDENCE.mkdir(parents=True, exist_ok=True)

    (EVIDENCE / name).write_text(json.dumps(data, indent=2), encoding="utf-8")





def remote(vm, script, label):

    windows = vm == "dnspoc-win"

    if windows:

        script = "$ErrorActionPreference = 'Stop'\n" + script + "\nWrite-Output 'DNSLAB_OK'\n"

    else:

        script = "set -eu\n" + script + "\necho DNSLAB_OK\n"

    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".ps1" if windows else ".sh", delete=False) as file:

        file.write(script)

        path = Path(file.name)

    try:

        result = az("vm", "run-command", "invoke", "-g", RG, "-n", vm,

                    "--command-id", "RunPowerShellScript" if windows else "RunShellScript", "--scripts", "@" + str(path))

    finally:

        path.unlink()

    save(f"{vm}-{label}-runcommand.json", result)

    stdout = "\n".join(v.get("message", "") for v in result.get("value", []))

    if "DNSLAB_OK" not in stdout:

        raise RuntimeError(f"Guest command failed on {vm}, phase {label}; inspect local Run Command evidence")

    print(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {vm} {label} OK", flush=True)

    return result





def encoded(path):

    return base64.b64encode(path.read_bytes()).decode("ascii")





def setup(vm):

    if vm == "dnspoc-win":

        return remote(vm, """

New-Item -ItemType Directory -Force C:\\dnslab | Out-Null

Get-Command pktmon.exe -ErrorAction Stop | Out-Null

Get-DnsClientServerAddress | Format-Table

""", "setup")

    common = """

export DEBIAN_FRONTEND=noninteractive

apt-get update -qq

apt-get install -y -qq tcpdump dnsutils python3 curl

mkdir -p /opt/dns-lab /var/lib/dns-lab

"""

    if vm == "dnspoc-ubuntu":

        return remote(vm, common + f"\necho '{encoded(ROOT / 'guest' / 'client-linux.py')}' | base64 -d > /opt/dns-lab/client.py\n", "setup")

    east = vm.endswith("east")

    ip = "10.10.2.4" if east else "10.30.2.4"

    answer = "192.0.2.10" if east else "192.0.2.20"

    script = common + f"""

echo '{encoded(ROOT / 'guest' / 'upstream.py')}' | base64 -d > /opt/dns-lab/upstream.py

echo healthy > /var/lib/dns-lab/mode

cat > /etc/systemd/system/dns-lab.service <<'UNIT'

[Unit]

Description=DNS failover lab authoritative upstream

After=network-online.target

[Service]

Environment=DNS_LAB_BIND={ip}

Environment=DNS_LAB_ANSWER={answer}

ExecStart=/usr/bin/python3 /opt/dns-lab/upstream.py

Restart=on-failure

User=root

[Install]

WantedBy=multi-user.target

UNIT

systemctl daemon-reload

systemctl enable dns-lab

systemctl restart dns-lab

systemctl is-active --quiet dns-lab

for attempt in 1 2 3 4 5; do

  if dig @{ip} setup.lab.failover.test A +tries=1 +time=1 +short | grep -Fx '{answer}'; then break; fi

  sleep 1

done

dig @{ip} setup.lab.failover.test A +tries=1 +time=2 +short | grep -Fx '{answer}'

"""

    return remote(vm, script, "setup")





def upload_linux(folder, blob):

    url = f"https://{STORAGE}.blob.core.windows.net/evidence/{RUN}/{blob}?{SAS}"

    return f"""

tar -czf /tmp/dns-lab-evidence.tar.gz -C '{folder}' .

curl --fail --silent --show-error --retry 3 -X PUT -H 'x-ms-blob-type: BlockBlob' --data-binary @/tmp/dns-lab-evidence.tar.gz '{url}'

rm /tmp/dns-lab-evidence.tar.gz

"""





def phase_client(vm, phase):

    if vm == "dnspoc-win":

        script = f"""

$env:DNS_LAB_PHASE = '{phase}'

$body = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded(ROOT / 'guest' / 'client-windows.ps1')}'))

try {{

    & ([scriptblock]::Create($body))

}} finally {{

    $archive = 'C:\\dnslab\\{phase}.zip'

    Compress-Archive -Path 'C:\\dnslab\\{phase}\\*' -DestinationPath $archive -Force

    Invoke-WebRequest -UseBasicParsing -Method Put -Headers @{{'x-ms-blob-type'='BlockBlob'}} -InFile $archive -Uri 'https://{STORAGE}.blob.core.windows.net/evidence/{RUN}/{vm}-{phase}.zip?{SAS}' | Out-Null

}}

"""

    else:

        script = f"""

echo '{encoded(ROOT / 'guest' / 'client-linux.py')}' | base64 -d > /opt/dns-lab/client.py

set +e

DNS_LAB_PHASE='{phase}' python3 /opt/dns-lab/client.py

result=$?

set -e

""" + upload_linux(f"/var/lib/dns-lab/{phase}", f"{vm}-{phase}.tar.gz") + "\ntest \"$result\" -eq 0\n"

    return remote(vm, script, phase)





def phase(phase_name):

    print(f"Starting {phase_name}", flush=True)

    with ThreadPoolExecutor(max_workers=2) as pool:

        futures = [pool.submit(phase_client, vm, phase_name) for vm in CLIENTS]

        errors = []

        for future in futures:

            try:

                future.result()

            except RuntimeError as exc:

                errors.append(str(exc))

        if errors:

            raise RuntimeError("; ".join(errors))





def health_gate(label):

    remote("dnspoc-ubuntu", """

successes=0

for attempt in $(seq 1 90); do

  name="health-$(date +%s%N).lab.failover.test"

  if answer=$(dig @168.63.129.16 "$name" A +tries=1 +time=5 +short); then

    printf 'Probe transport completed\\n'

  else

    printf 'Probe transport failed with exit %s\\n' "$?"

  fi

  printf '%s %s %s\\n' "$(date -u +%FT%TZ)" "$name" "$answer"

  if [ "$answer" = "192.0.2.10" ]; then

    successes=$((successes + 1))

    if [ "$successes" -ge 2 ]; then break; fi

  else

    successes=0

  fi

  sleep 5

done

if [ "$successes" -lt 2 ]; then

  echo 'East primary did not regain healthy forwarding' >&2

  exit 1

fi

""", f"health-{label}")





RESTORE_EAST = """

systemctl list-units --all --plain --no-legend 'dns-lab-rollback-*.timer' | awk '{print $1}' | xargs -r systemctl stop

echo healthy > /var/lib/dns-lab/mode

for p in udp tcp; do

  if iptables -C INPUT -s 10.10.1.0/28 -p "$p" --dport 53 -m comment --comment dns-lab-outbound-drop -j DROP 2>/dev/null; then

    iptables -D INPUT -s 10.10.1.0/28 -p "$p" --dport 53 -m comment --comment dns-lab-outbound-drop -j DROP

  fi

done

"""





def upstream_fault(mode, context=""):

    if mode not in ("drop", "servfail", "restore"):

        raise ValueError(mode)

    script = "iptables -L INPUT -n -v\n" + RESTORE_EAST

    if mode != "restore":

        rollback64 = base64.b64encode(("set -eu\n" + RESTORE_EAST).encode()).decode()

        script += f"""

echo '{rollback64}' | base64 -d > /opt/dns-lab/restore.sh

systemd-run --unit=dns-lab-rollback-$(date +%s) --on-active=8m /bin/sh /opt/dns-lab/restore.sh

"""

        if mode == "servfail":

            script += "\necho servfail > /var/lib/dns-lab/mode\n"

        else:

            script += """

for p in udp tcp; do

  iptables -I INPUT -s 10.10.1.0/28 -p "$p" --dport 53 -m comment --comment dns-lab-outbound-drop -j DROP

done

"""

    script += f"""

python3 -c 'import datetime,json; print(json.dumps({{"event":"{mode}","utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}}))' >> /var/lib/dns-lab/faults.jsonl

iptables -L INPUT -n -v

cat /var/lib/dns-lab/mode

"""

    return remote("dnspoc-up-east", script, f"{context}-fault-{mode}")





def peer_restore():

    for vnet, name, target in (("dnspoc-east-spoke", "to-east", "dnspoc-east-hub"),

                               ("dnspoc-east-hub", "to-spoke", "dnspoc-east-spoke")):

        az("network", "vnet", "peering", "create", "-g", RG, "--vnet-name", vnet, "-n", name,

           "--remote-vnet", target, "--allow-vnet-access")

    save("peerings-restored.json", az("network", "vnet", "peering", "list", "-g", RG, "--vnet-name", "dnspoc-east-spoke"))





def peer_remove():

    for vnet, name in (("dnspoc-east-spoke", "to-east"), ("dnspoc-east-hub", "to-spoke")):

        az("network", "vnet", "peering", "delete", "-g", RG, "--vnet-name", vnet, "-n", name)

    save("peerings-removed.json", az("network", "vnet", "peering", "list", "-g", RG, "--vnet-name", "dnspoc-east-spoke"))

    ruleset_id = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RG}/providers/Microsoft.Network/dnsForwardingRulesets/dnspoc-east-ruleset"

    save("east-ruleset-links-during-no-peering.json", az("rest", "--method", "get",

         "--url", f"https://management.azure.com{ruleset_id}/virtualNetworkLinks?api-version=2022-07-01"))





def collect():

    for vm in ("dnspoc-up-east", "dnspoc-up-west"):

        remote(vm, upload_linux("/var/lib/dns-lab", f"{vm}-logs.tar.gz"), "collect")

    # Download via account login/key in the local CLI, never make the container public.

    az("storage", "blob", "download-batch", "--account-name", STORAGE, "--auth-mode", "key",

       "--source", "evidence", "--destination", str(EVIDENCE), "--pattern", f"{RUN}/*", "--no-progress")

    for archive in (EVIDENCE / RUN).glob("*"):

        destination = EVIDENCE / "extracted" / archive.name.split(".")[0]

        destination.mkdir(parents=True, exist_ok=True)

        if archive.suffix == ".zip":

            with zipfile.ZipFile(archive) as stream:

                stream.extractall(destination)

        elif archive.name.endswith(".tar.gz"):

            with tarfile.open(archive) as stream:

                stream.extractall(destination, filter="data")





def main():

    global STORAGE, SAS, RUN, EVIDENCE

    parser = argparse.ArgumentParser()

    parser.add_argument("--skip-setup", action="store_true")

    parser.add_argument("--phases", nargs="+", default=["baseline", "primary-timeout", "east-servfail", "east-outbound-drop", "no-east-peering", "recovery"])

    parser.add_argument("--run-id")

    parser.add_argument("--subscription", default=os.environ.get("AZURE_SUBSCRIPTION_ID"),

                        help="Subscription ID/name; defaults to AZURE_SUBSCRIPTION_ID or the current Azure CLI account")

    parser.add_argument("--resource-group", default=RG)

    parser.add_argument("--deployment-name", default="dns-crossregion-poc")

    args = parser.parse_args()

    if args.run_id:

        RUN = args.run_id

        EVIDENCE = ROOT / "evidence" / RUN

    configure_context(args.subscription, args.resource_group)

    STORAGE = az("deployment", "group", "show", "-g", RG, "-n", args.deployment_name)["properties"]["outputs"]["storageAccount"]["value"]

    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=4)).strftime("%Y-%m-%dT%H:%MZ")

    SAS = az("storage", "container", "generate-sas", "--account-name", STORAGE, "--name", "evidence",

             "--permissions", "cw", "--expiry", expiry, "--https-only", "--auth-mode", "key")

    save("manifest.json", {"runId": RUN, "subscription": SUBSCRIPTION, "resourceGroup": RG, "storage": STORAGE,

         "phases": args.phases, "startedUtc": dt.datetime.now(dt.timezone.utc).isoformat(),

         "primary": "168.63.129.16", "secondary": "10.30.0.4", "eastAnswer": "192.0.2.10", "westAnswer": "192.0.2.20",

         "primaryOverrides": {"fast-servfail-control": "10.10.2.4"}})

    print(f"Evidence: {EVIDENCE}", flush=True)

    try:

        if not args.skip_setup:

            with ThreadPoolExecutor(max_workers=4) as pool:

                list(pool.map(setup, (*CLIENTS, "dnspoc-up-east", "dnspoc-up-west")))

        for name in args.phases:

            health_gate(name)

            if name in ("east-outbound-drop", "east-servfail", "fast-servfail-control"):

                upstream_fault("drop" if name == "east-outbound-drop" else "servfail", name)

                try:

                    phase(name)

                finally:

                    upstream_fault("restore", name)

            elif name == "no-east-peering":

                try:

                    peer_remove()

                    time.sleep(20)

                    phase(name)

                finally:

                    peer_restore()

            else:

                phase(name)

    finally:

        collect()

    save("completed.json", {"utc": dt.datetime.now(dt.timezone.utc).isoformat(), "status": "completed"})

    print(f"Completed: {EVIDENCE}", flush=True)





if __name__ == "__main__":

    main()

