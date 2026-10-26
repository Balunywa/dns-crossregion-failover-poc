# DNS cross-region failover: measured results

**New to this lab?** Read [the scenario-by-scenario architecture guide](./SCENARIOS.md)
for what DNS is doing, the role of every component, the normal and faulted paths,
and exactly what each result proves. You do not need to infer the architecture
from the numbers in this report.

**Test date:** 2026-10-26, approximately 14:02-14:19 UTC.  
**Authoritative run:** `final-validation`.  
**Deployment:** `original-test-subscription-redacted` / `rg-dns-crossregion-failover-poc`.  
**Clients:** Windows Server 2022 and Ubuntu 24.04, both in East US.  
**Normal DNS order:** Azure DNS `168.63.129.16`, then West inbound `10.30.0.4`.

## Summary

All three requested fault conditions were executed on both operating systems.
The clean final run contains **210 main-scenario native lookups, zero failures**,
and **zero packet-decode errors** across 14 client/scenario combinations.
An additional 12 native lookups surround the primary-timeout injection:
three before and three after on each OS; all also succeeded.

Successful main-scenario answers were independently corroborated by upstream logs,
not just by explicit queries to each DNS server. Both upstreams are healthy and
all four directional VNet peerings were verified Connected after testing.

**Conclusion:** both tested client stacks used the West path when the primary
timed out or East forwarding failed. East ruleset resolution also survived removal
of East hub peering. These are measured POC outcomes, not a universal client
failover guarantee or production availability SLA.

## Requested test cases and results

Expected Result is the target behavior being tested, not an assumed Azure guarantee.
Each fault variant includes 15 native lookups per OS. Failover times below are the
first faulted lookup's API completion time, not control-plane fault-injection RTO.

| Test ID | Scenario | Description | Steps | Expected Result | Actual Result |
|---|---|---|---|---|---|
| [**TC-01**](./SCENARIOS.md#tc-01-the-workload-cannot-get-a-response-from-primary-azure-dns) | Primary Azure DNS timeout | Both clients are in East US. Normal path: workload -> Azure DNS -> linked East ruleset -> East outbound -> East upstream. We break only workload access to the primary DNS address; the independent West path stays connected. | 1. Set Azure DNS primary and West inbound secondary. 2. Block UDP/TCP port 53 to `168.63.129.16` on each workload. 3. Run native lookups and capture retries. 4. Remove firewall rules. | The OS selects its backup: workload -> global peering -> West inbound -> West ruleset/outbound -> West upstream. No application retry code is added. | **PASS - both OSes.** Windows: first West lookup **1.088 s**. Ubuntu: **10.082 s**. Each OS: **15/15 West answers; zero failures**. |
| [**TC-02**](./SCENARIOS.md#tc-02-azure-dns-is-reachable-but-its-east-forwarding-path-cannot-answer) | East forwarding fails while Azure DNS remains reachable | The workload-to-Azure-DNS path stays healthy. The break is farther downstream: East outbound -> East upstream. West has its own ruleset, outbound endpoint and upstream, so it does not share this failed dependency. | 1. Keep Azure DNS reachable. 2. In variant A, drop East-outbound-subnet DNS at the East upstream firewall. 3. In separate variant B, let the reachable upstream return SERVFAIL. 4. Capture native lookups and response/request ordering. 5. Restore the upstream after each variant. | The client can use workload -> global peering -> West inbound -> West ruleset/outbound -> West upstream when East cannot supply an answer. | **PASS - both OSes, both variants.** Forwarding drop: Windows **1.105 s**, Ubuntu **5.079 s**. Upstream SERVFAIL through Azure: Windows **1.109 s**, Ubuntu **5.075 s**. Each variant/OS: **15/15 West answers; zero failures**. West was tried **before Azure's SERVFAIL arrived**: timeout-driven fallback, not proof of a SERVFAIL-triggered switch. |
| [**TC-03**](./SCENARIOS.md#tc-03-remove-the-east-workload-to-hub-network-peering) | East hub peering removed | We remove the workload/East-hub network connection, not the DNS ruleset link. Azure DNS can still apply that link. The East outbound and upstream stay together inside the East hub; their path is unchanged. | 1. Retain the East ruleset link and West peering. 2. Remove both directional East workload/hub peerings. 3. Run fresh native lookups. 4. Separately query East inbound directly. 5. Restore peering. | Native path remains workload -> Azure DNS -> linked East ruleset -> East outbound -> East upstream; West fallback is unnecessary. Direct workload-to-East-inbound access is a different, now-broken path. | **PASS - both OSes.** Each OS: **15/15 East answers; zero failures**. Median lookup: Windows **9.8 ms**, Ubuntu **9.9 ms**. Direct East inbound diagnostics timed out as expected; these are not native workload failures. All peerings were restored. |

**TC-02 qualification:** the real Azure-path tests do not prove that SERVFAIL
triggered the switch, because the West request occurred first. A separate
fast-SERVFAIL client-policy control temporarily used the East upstream directly
as primary, rather than Azure DNS. Both OSes then queried West **after receiving
SERVFAIL**: Windows **109.9 ms**, Ubuntu **86.3 ms** for the first successful lookup.
The detailed matrix below separates that control from the three requested cases.

## Detailed test matrix and supplementary controls

Each main case contains **15 fresh native lookups per OS**. Timing is the first
fault lookup's native API elapsed time for failover cases, or median lookup
latency for healthy cases. It is not the Azure control-plane fault-injection RTO.

| # | Test case and injected condition | Windows Server result | Ubuntu result | Failures, Windows / Ubuntu | Finding |
|---|---|---|---|---|---|
| 1 | Healthy baseline: primary Azure DNS, independent West secondary | East 15/15; median **10.6 ms** | East 15/15; median **9.1 ms** | 0/15 / 0/15 | Native clients actually selected East; explicit diagnostics separately verified West |
| 2 | Primary Azure DNS timeout: guest firewall drops UDP and TCP DNS to `168.63.129.16` | West 15/15; first lookup **1.088 s** | West 15/15; first lookup **10.082 s** | 0/15 / 0/15 | Both clients fail over, with substantially different delay |
| 3 | Fast-SERVFAIL client-policy control: temporarily use reachable East upstream `10.10.2.4` as primary | West 15/15; first lookup **109.9 ms** | West 15/15; first lookup **86.3 ms** | 0/15 / 0/15 | Both issued a West request after receiving primary SERVFAIL; synthetic control, not the Azure primary path |
| 4 | Reachable East upstream emits SERVFAIL through the real Azure DNS path | West 15/15; first lookup **1.109 s** | West 15/15; first lookup **5.075 s** | 0/15 / 0/15 | Both switched before Azure's client-facing SERVFAIL arrived; timeout-driven fallback |
| 5 | East outbound forwarding fails: upstream firewall drops DNS from `10.10.1.0/28`, while Azure DNS remains reachable | West 15/15; first lookup **1.105 s** | West 15/15; first lookup **5.079 s** | 0/15 / 0/15 | Client-side West fallback works despite a reachable but unsuccessful primary |
| 6 | Remove both East spoke/hub directional peerings, retaining East ruleset link and West peerings | East 15/15; median **9.8 ms** | East 15/15; median **9.9 ms** | 0/15 / 0/15 | Linked ruleset resolution does not require East spoke/hub peering |
| 7 | Final recovery: healthy upstreams, restored peerings, DNS order reapplied and caches reset | East 15/15; median **9.8 ms** | East 15/15; median **9.7 ms** | 0/15 / 0/15 | Restored configuration resolves through East; this is not an unassisted failback measurement |
| 8 | Immediate post-primary-timeout restoration, without forcing a new server preference | East **3/3** | West **3/3** | 0/3 / 0/3 | Windows returned to East in these probes; Ubuntu remained on West. Restoring the primary does not imply immediate failback |

Immediately before case 2, each OS also resolved three fresh names through East
successfully. These six pre-fault probes and the six probes in case 8 are outside
the 210 main-scenario lookup count.

### Complete latency distribution

With only 15 serial samples, nearest-rank p95 is the largest sample. Do not read
these numbers as a statistically established production percentile.

| Scenario | Windows p50 / p95 (ms) | Ubuntu p50 / p95 (ms) |
|---|---:|---:|
| Baseline | 10.6 / 54.5 | 9.1 / 19.4 |
| Primary timeout | 70.6 / 1088.5 | 74.4 / 10082.4 |
| Fast-SERVFAIL control | 72.3 / 109.9 | 75.7 / 86.3 |
| East upstream SERVFAIL through Azure | 75.1 / 1109.3 | 73.8 / 5075.4 |
| East outbound-path drop | 72.1 / 1105.0 | 73.6 / 5079.5 |
| No East hub peering | 9.8 / 41.7 | 9.9 / 14.3 |
| Final recovery | 9.8 / 47.1 | 9.7 / 19.3 |

After the first slow fault lookup, West-served calls were generally around
70-76 ms median. A zero failure count therefore does not mean no user-visible
delay: the first Ubuntu timeout lookup took approximately ten seconds.

## Packet-level retry and negative-response ordering

The following times are relative to the first native lookup's recorded UTC start.
The native API stopwatch and packet wall-clock measurements have slightly
different start overhead; sub-millisecond arithmetic between the two is not an SLA.

| Scenario / OS | First primary SERVFAIL received | First West request emitted | First native West completion | Interpretation |
|---|---:|---:|---:|---|
| Primary timeout / Windows | None; primary DNS blocked | 1003.7 ms | 1088.5 ms API time | West request follows the client timeout; blocked primary packets do not reach NIC capture |
| Primary timeout / Ubuntu | None; primary DNS blocked | 10010.6 ms | 10082.4 ms API time | Approximately ten-second native delay before West |
| East outbound drop / Windows | 8551.0 ms | 1032.5 ms | 1105.0 ms API time | West was selected well before late primary SERVFAIL |
| East outbound drop / Ubuntu | 7886.9 ms | 5006.6 ms | 5079.5 ms API time | Same ordering; longer client timer |
| East upstream SERVFAIL / Windows | 5378.5 ms | 1033.9 ms | 1109.3 ms API time | Upstream SERVFAIL did not immediately propagate through Azure |
| East upstream SERVFAIL / Ubuntu | 6013.4 ms | 5004.9 ms | 5075.4 ms API time | West request preceded Azure's SERVFAIL |
| Fast-SERVFAIL control / Windows | 42.670 ms | 42.928 ms | 109.9 ms API time | Primary negative response preceded West request |
| Fast-SERVFAIL control / Ubuntu | 7.122 ms | 12.099 ms | 86.3 ms API time | Primary negative response preceded West request |

The synthetic fast-SERVFAIL control bypasses Azure DNS for its primary only.
It answers the client-policy question that the real Azure SERVFAIL experiment
alone could not isolate. It must not be presented as an Azure service response-time
measurement.

For the first faulted A query:

- East outbound drop: primary-to-West request spacing was **998.4 ms Windows**
  and **5004.2 ms Ubuntu**.
- East upstream SERVFAIL: spacing was **1002.1 ms Windows** and **5002.5 ms Ubuntu**.
- Fast-SERVFAIL control: spacing was **7.624 ms Windows** and **9.992 ms Ubuntu**;
  Ubuntu emitted three primary A requests before its West request.
- Primary timeout: a primary-to-West wire interval is unavailable because the
  guest firewall drops primary requests before NIC capture. Native-start-to-West
  timing and the firewall state provide the meaningful measurement.

For the guest-local primary timeout, fault-record-to-first-West-completion was
approximately **1.098 s Windows** and **10.083 s Ubuntu**. Central upstream faults
use Azure Run Command and have variable controller-to-client delays; their
fault-onset-to-recovery wall-clock time is deliberately not claimed.

## Peering-removal and restoration evidence

- During case 6, the East spoke/hub peerings were absent, the West peering remained,
  and the East forwarding-ruleset spoke link remained present.
- Native East answers succeeded for all 30 workload queries.
- Direct East inbound diagnostics to `10.10.0.4`, performed afterward, timed out:
  Windows error **1460**, Ubuntu `dig` exit **9**. This is an expected diagnostic
  timeout, not a native workload query failure.
- The East upstream drop rule counted **36 dropped UDP DNS packets** from the
  outbound subnet; the TCP drop rule was installed but counted zero packets.
  Post-restoration firewall output showed both rules removed.
- Both archived upstream mode files ended in `healthy`.
- Final ARM verification showed all four directional peerings `Connected`.
- The recovery-phase OS configurations show Azure DNS primary and West secondary.

## Evidence index

All paths below are relative to this deliverable.

| Evidence | Location |
|---|---|
| Machine-readable results, native calls, retry timings, direct diagnostics | [summary.json](./evidence/final-validation/summary.json) |
| Exact 210-sample integrity checks, zero decode errors and upstream corroboration | [validation.json](./evidence/final-validation/validation.json) |
| Run identity, address fingerprints, phase list and synthetic primary override | [manifest.json](./evidence/final-validation/manifest.json) |
| Harness completion marker | [completed.json](./evidence/final-validation/completed.json) |
| Final peering verification | [final-peering-verification.json](./evidence/final-validation/final-peering-verification.json) |
| Peerings absent during test | [peerings-removed.json](./evidence/final-validation/peerings-removed.json) |
| East ruleset links retained during test | [east-ruleset-links-during-no-peering.json](./evidence/final-validation/east-ruleset-links-during-no-peering.json) |
| Upstream packet-drop counters and restoration | [drop fault restoration output](./evidence/final-validation/dnspoc-up-east-east-outbound-drop-fault-restore-runcommand.json) |
| Per-OS/per-phase native JSONL, original captures, decoded packets and configuration | [extracted/](./evidence/final-validation/extracted/) |
| Original uploaded ZIP/tar/ETL archives | Kept privately; omitted from this public export |
| End-to-end architecture, client stacks and sequence diagrams | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| Standalone rendered topology map | [architecture.svg](./architecture.svg) |

Example captured native names, directly searchable in the corresponding JSONL,
packet capture and upstream log:

- Windows forwarding drop:
  `east-outbound-drop-fault-0-b791fafe66.lab.failover.test`
- Ubuntu forwarding drop:
  `east-outbound-drop-fault-0-9646cb4c11.lab.failover.test`
- Windows fast-SERVFAIL control:
  `fast-servfail-control-fault-0-df59c292b4.lab.failover.test`
- Ubuntu fast-SERVFAIL control:
  `fast-servfail-control-fault-0-7656649fd9.lab.failover.test`

## Method, validation and limitations

- Windows uses native `.NET Dns.GetHostAddresses`; Ubuntu uses libc/NSS and
  systemd-resolved via `socket.getaddrinfo(AF_INET)`.
- Each region has exactly one forwarding destination and a separate upstream VM.
  East returns `192.0.2.10`; West returns `192.0.2.20`.
- Unique labels and zero-TTL A records prevent positive-cache false positives.
- Fifteen serial main queries run per OS/phase, paced 500 ms apart.
- Explicit server probes run after native streams and do not establish fallback.
- A healthy East gate runs before every phase to avoid previous upstream-failure
  state contaminating the next case.
- An initial Dsv5 quota failure was resolved using B-series VMs within quota.
- Exploratory runs exposed query-log accumulation and buffered capture shutdown;
  both were fixed before this clean run. Headline metrics use only
  `final-validation`, not accumulated exploratory baselines.
- Eleven local responder/decoder unit tests passed; Bicep compiled and deployed.
  SVG XML parsing and browser rendering were also checked.
- Managed resolver internal retries are not directly instrumented. Client captures,
  upstream query logs and regional answer fingerprints are the evidence sources.
- The decoder does not reassemble multi-segment TCP DNS and exposes parse errors.
  No decode errors occurred in this run; raw captures remain authoritative.
- Only these OS images/configurations were exercised. Full region outages, both
  DNS servers unavailable, NXDOMAIN client policy, load, packet loss distributions,
  application reconnect behavior and long-term unassisted failback were not tested.

Reference design: [Daniel Mauser's ruleset failover lab](https://github.com/dmauser/az-dnsruleset-failover).  
Azure ruleset-link behavior: [Microsoft Learn](https://learn.microsoft.com/en-us/azure/dns/private-resolver-endpoints-rulesets).

## Reproduce and clean up

See [README.md](./README.md) for deployment, watchdogs and cleanup.
To reproduce the authoritative seven-phase sequence:

```powershell
python .\run_lab.py --skip-setup --phases baseline primary-timeout fast-servfail-control east-servfail east-outbound-drop no-east-peering recovery --run-id repeat-validation
python .\validate_evidence.py .\evidence\repeat-validation
```

Omit `--skip-setup` for a freshly deployed lab. Use a new run ID each time to
preserve previous evidence.

**The lab remains deployed and billable.** Download the evidence before deleting
the dedicated resource group. No unrelated subscription resources were modified.
