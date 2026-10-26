# Azure client-side cross-region DNS failover POC



## Scope



This is a disposable, chargeable Azure lab, not a production DNS architecture.

It tests native Windows Server 2022 and Ubuntu 24.04 client resolver behavior with

`168.63.129.16` first and a West US Private Resolver inbound endpoint (`10.30.0.4`)

second. No application-level retry or failover algorithm is added.



See [end-to-end architecture and sequence diagrams](./ARCHITECTURE.md) and

[measured results](./RESULTS.md).



Reference: [Daniel Mauser's forwarding-ruleset failover lab](https://github.com/dmauser/az-dnsruleset-failover).

That lab tests multiple upstream destinations in one forwarding rule. This POC

deliberately has **one destination per regional rule**, so upstream-destination

failover cannot masquerade as client-side cross-region failover.



## Topology



```text

East US spoke 10.20.0.0/16

  Windows 10.20.0.4 / Ubuntu 10.20.0.5

  NIC DNS [168.63.129.16, 10.30.0.4]

  linked to East ruleset; independently peered to both regional hubs



East US hub 10.10.0.0/16           West US hub 10.30.0.0/16

  inbound 10.10.0.4                 inbound 10.30.0.4

  outbound 10.10.1.0/28             outbound 10.30.1.0/28

  upstream 10.10.2.4                upstream 10.30.2.4

  lab.failover.test -> upstream     lab.failover.test -> upstream

  answer 192.0.2.10                 answer 192.0.2.20

  ruleset links: hub, East spoke    ruleset links: West hub

```



Each upstream is a separate Ubuntu VM with a lab-only UDP/TCP DNS responder.

Unique query labels and zero-TTL A records avoid positive-cache false positives.

The region-identifying addresses are documentation addresses, not application

endpoints. The servers return AAAA NODATA and can inject SERVFAIL.



The West ruleset is not linked across regions: Azure does not support that.

The East clients reach the West inbound endpoint over global VNet peering.

The East ruleset link uses Azure's DNS service path, not the spoke/hub peering.



## Deployment



Prerequisites: authenticated Azure CLI, Bicep, local Python 3.12+, PowerShell,

appropriate network/compute/storage deployment and VM Run Command permissions,

6 available B-series cores in East US and 2 in West US.



```powershell

az login

az account show --query "{name:name,id:id}" -o table

.\deploy.ps1

python .\run_lab.py

```



There is no embedded subscription, tenant, credential or storage account.

Both entry points accept an explicit subscription ID/name, otherwise use

`AZURE_SUBSCRIPTION_ID` if set, otherwise resolve the current Azure CLI account.

After resolution every Azure command is pinned to the resolved subscription ID,

without changing the caller's active Azure account.



To use a specific subscription and a custom resource group:



```powershell

$subscription = '<your-subscription-id-or-name>'

$resourceGroup = 'rg-my-dns-failover-lab'

.\deploy.ps1 -Subscription $subscription -ResourceGroup $resourceGroup

python .\run_lab.py --subscription $subscription --resource-group $resourceGroup

```



Use matching resource-group and subscription arguments for deployment and tests.

Both entry points also accept a deployment name (`-DeploymentName` /

`--deployment-name`, default `dns-crossregion-poc`). The runner reads its storage

account from that deployment's outputs. Bicep generates a globally unique storage

name from the resource-group ID. East/West VM sizes can be changed using

`-EastSize` and `-WestSize` if your subscription has different quota or capacity.

The default resource group is `rg-dns-crossregion-failover-poc`. Network addresses

are intentionally a fixed, isolated lab topology; the regions remain East US

and West US because cross-region behavior is the experiment.



Four standard public IPs provide explicit guest egress for package installation

and evidence upload. NSGs deny Internet inbound access. There is no open RDP or

SSH access; management uses Azure VM Run Command. Generated admin credentials

are not printed or kept in source; use Azure VM password reset if interactive

access is needed. Evidence is in a private Storage container. Upload-only,

HTTPS-only, four-hour SAS tokens are passed transiently through Run Command,

whose privileged guest script cache may retain them until expiry. Do not share

Run Command request payloads.



## Tests and restoration



1. **Baseline:** native OS resolution and separate explicit-server diagnostics.

2. **Primary timeout:** guest firewall drops UDP and TCP port 53 to

   `168.63.129.16` only. Three healthy native calls precede the fault, followed

   by 15 fault calls and three recovery calls. Other Azure platform traffic is

   not blocked. Guest watchdog restores the firewall after eight minutes.

3. **East outbound-path drop:** upstream firewall drops DNS only from the East

   outbound endpoint subnet. Azure DNS remains reachable. The primary's actual

   response, including SERVFAIL if returned, is captured. This is an upstream-side

   selective network fault, not a deletion of the managed outbound endpoint.

4. **Explicit East SERVFAIL:** upstream remains reachable and responds SERVFAIL.

   This separates a negative DNS response from silent network failure.

5. **East peering removal:** both directions of East spoke/hub peering are

   removed; East ruleset link and West peering remain. Fresh unique names ensure

   that continued East answers are not client-cache hits.

6. **Recovery:** healthy configuration and native queries after restoration.



An optional **`fast-servfail-control`** temporarily uses the reachable East

upstream (`10.10.2.4`) as the OS primary, with West still secondary, and has that

server return immediate SERVFAIL. Both clients restore Azure DNS as primary in

`finally`. This is explicitly a synthetic **client-policy control**, not a claim

that Azure DNS emits immediate SERVFAIL. It distinguishes response-driven fallback

from a client timer firing before Azure finishes its own upstream retry cycle.

Run it with `--phases fast-servfail-control`; it is not in the default core suite.



The harness uses `finally` for upstream and peering restoration. Upstream faults

also have an eight-minute guest watchdog. A terminated controller cannot restore

peering automatically; rerun the Bicep deployment to reconcile peerings.

Run Command operations need working Azure guest agents and can take minutes.

Before every phase, a health gate requires two fresh East answers from the primary.

This avoids mistaking a previous fault's upstream backoff for a new fault's effect.

The default order exercises explicit SERVFAIL before the forwarding-path drop.



To rerun without guest setup:



```powershell

python .\run_lab.py --skip-setup --phases baseline primary-timeout east-outbound-drop east-servfail no-east-peering recovery

python .\analyze.py .\evidence\<run-id>

python .\validate_evidence.py .\evidence\<run-id>

```



## Evidence and measurement integrity



Per phase and OS, the private evidence container and local download contain:



- Native API results, unique names, UTC start/end stamps, API latency and errors.

- Windows `pktmon` ETL, pcapng, packet text and OS/DNS configuration.

- Ubuntu `tcpdump` pcap, packet text and systemd-resolved configuration.

- Explicit-server diagnostics, run separately **after** the native query stream.

- Independent upstream query logs with source IPs, RCODE and answer fingerprints.

- Fault/restoration Run Command outputs, firewall counters and peering snapshots.

- A run manifest and completion marker, written only after successful execution.



`validate_evidence.py` checks exactly 15 fault/healthy calls per OS/phase, unique

names, zero packet-decode errors and successful-answer corroboration in the

independent upstream logs. A measured native query failure is not itself an

evidence-integrity failure.



Windows uses .NET `Dns.GetHostAddresses`, not `nslookup`. Ubuntu uses Python's

`socket.getaddrinfo(AF_INET)` through the image's libc/NSS/systemd-resolved path.

Ubuntu systemd-resolved is restarted and its per-link server order is set before

each phase; Windows DNS addresses are reapplied and its cache flushed. Server

preference is stateful: do not interpret post-fault West stickiness as failback.

Configuration resets are not proof of first-server selection; inspect the wire.



There are 15 serial calls per phase with 500 ms pacing. This is a behavioral POC,

not a load test, a production SLA or a statistically robust regional-outage test.

First-West native-call latency measures a fresh lookup's observed service delay.

Where both requests are emitted, decoded packets also measure primary-to-West

request delay. These are **not** controller-fault-to-recovery wall-clock times:

Azure Run Command introduces a variable delay between upstream fault injection

and the first client query. Guest-local primary-timeout timestamps do permit

fault-onset comparison.



The packet decoder supports IPv4 DNS over UDP and complete single-segment TCP

messages. It emits explicit decode errors, rather than silently claiming complete

coverage. Raw captures remain authoritative. Windows may emit AAAA alongside A;

wire summaries restrict comparison to A queries. Packets dropped before NIC

capture may not be visible, so absence of a primary packet does not prove no

client attempt. Explicit probes alone never prove native fallback.



## Local checks



```powershell

az bicep build --file .\infra\main.bicep --stdout

python -m unittest discover -s . -p 'test_*.py' -v

```



## Cleanup



Download evidence before deleting. This deletes only the dedicated lab group:



```powershell

$subscription = az account show --query id -o tsv

$resourceGroup = 'rg-dns-crossregion-failover-poc'

az group delete --subscription $subscription --name $resourceGroup --yes --no-wait

```



If you supplied a different subscription or resource group when deploying, use

those exact values above instead. Confirm the target group before deleting it.



Private Resolver endpoints, four VMs/disks, public IPs, storage and cross-region

traffic incur charges while the lab exists. Deallocating VMs does not stop

resolver endpoint or disk charges.



## Public evidence snapshot

The committed `evidence/final-validation` snapshot contains measured native
results, independent upstream logs, and packet captures filtered to the isolated
`lab.failover.test` namespace. Subscription and storage identifiers are redacted.
Original ZIP/tar/ETL archives and unrelated background DNS traffic are not
published. Filtered packets preserve the lab DNS request/response traffic;
nanosecond pcapng timestamp serialization can change sub-microsecond rounding.
Run `python .\validate_evidence.py .\evidence\final-validation` to recompute
and validate the published data. New test runs produce your own full private
captures locally and in your deployment's private storage account.

The checked-in results describe the original experiment, not a promise of
identical timings in your subscription. Current scripts additionally make Azure
subscription/resource-group selection portable; their context-selection tests
run without deploying resources.
