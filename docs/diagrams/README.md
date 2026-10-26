# Architecture drawings

These are original drawings of **this lab**, using the same general drawing
workflow as [Daniel Mauser's reference diagram](https://github.com/dmauser/azure-dnsresolver-failover/tree/main/docs/diagrams):
editable diagrams.net/draw.io XML, Azure product icons, region/VNet/subnet
boundaries, routed connectors, and clearly marked faults.

The topology is deliberately different: our primary is Azure DNS
`168.63.129.16`, and our workload VNet has direct global peering to West.
There are no NVAs, hub-to-hub peering, or on-premises sites in this experiment.

## Open the drawings

| Drawing | View | Vector | Editable |
|---|---|---|---|
| Full architecture | [PNG](./architecture-overview.png) | [SVG](./architecture-overview.svg) | Overview page in the draw.io file below |
| TC-01: primary DNS timeout at client | [PNG](./tc-01-primary-timeout.png) | [SVG](./tc-01-primary-timeout.svg) | TC-01 page |
| TC-02: East forwarding failure | [PNG](./tc-02-forwarding-failure.png) | [SVG](./tc-02-forwarding-failure.svg) | TC-02 page |
| TC-03: East peering removed | [PNG](./tc-03-peering-removal.png) | [SVG](./tc-03-peering-removal.svg) | TC-03 page |

Download [dns-failover-scenarios.drawio](./dns-failover-scenarios.drawio) and open
it in the draw.io desktop application or [diagrams.net](https://app.diagrams.net/).
Select a page along the bottom. Text, icons, containers, fault markers and lines
are separate editable objects, not a flattened screenshot.

The icons are embedded in both the draw.io file and the SVGs. The published
diagrams do not depend on a particular user's local installation paths.

## Regenerate

No third-party Python packages are needed:

```powershell
python .\docs\diagrams\build_architecture_diagrams.py
```

This regenerates all SVGs, the four-page editable draw.io file, and the root
`architecture.svg` compatibility link target. The drawing geometry is defined
once and shared by the draw.io and SVG exporters.

PNG previews are browser-rendered from the SVGs. To export PNGs after editing
in draw.io, use **File -> Export as -> PNG**; use a scale of 2 for crisp labels.
The Azure deployment and DNS test scripts do not depend on any drawing tools.

Validate the editable hierarchy, embedded icons, scenario fault markers and
that the committed vector exports match the generator:

```powershell
python -m unittest discover -s .\docs\diagrams -p test_diagrams.py -v
```

## Reading conventions

- Blue arrows: DNS request/processing path.
- Purple dashed arrow: Azure DNS ruleset service association, not peering.
- Orange dashed line: the West backup path is available but not the path used
  for the native lookups shown in that scenario.
- Green line: the West path used during TC-01/TC-02.
- Grey dashed line: the separate East spoke/hub peering relationship.
- Red cross: exact injected failure location.
- Answers `192.0.2.10` and `192.0.2.20` identify East and West; they are not
  application endpoints.

The same layouts are reused across scenario pages so the reader can see what
changes without having to learn a new topology each time. Measured results and
limitations are printed below each diagram.

## Icon attribution and use

Azure product icons are Microsoft's architecture icons, provided unmodified
through the [diagrams.net Azure icon library](https://github.com/jgraph/drawio/tree/dev/src/main/webapp/img/lib/azure2).
They are used here only to identify the Azure products in architectural diagrams.
See Microsoft's [Azure icon guidelines and permitted use](https://learn.microsoft.com/en-us/azure/architecture/icons/).

| Local asset | Library source |
|---|---|
| `assets/virtual-network.svg` | `networking/Virtual_Networks.svg` |
| `assets/virtual-machine.svg` | `compute/Virtual_Machine.svg` |
| `assets/dns-private-resolver.svg` | `networking/DNS_Private_Resolver.svg` |
| `assets/azure-dns.svg` | `networking/DNS_Zones.svg` |

The scene generator and topology drawings are original work for this POC;
Daniel's topology/source code is not copied.
