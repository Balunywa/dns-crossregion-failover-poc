"""Generate original editable draw.io pages and self-contained SVG architecture views."""
import base64
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1880, 1220
BLUE, PURPLE, GREEN = "#0078D4", "#8764B8", "#107C10"
ORANGE, RED, GREY, TEXT = "#CA5010", "#C4262E", "#8A8886", "#242424"


@dataclass
class Shape:
    name: str
    kind: str
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    parent: str = "1"
    text: tuple = ()
    color: str = TEXT
    fill: str = "none"
    stroke: str = "none"
    size: int = 16
    bold: bool = False
    dashed: bool = False
    thickness: float = 1.5
    arrow: bool = False
    asset: str = ""
    points: list = field(default_factory=list)


class Scene:
    def __init__(self, name, title):
        self.name, self.title = name, title
        self.shapes = []

    def add(self, kind, name, x=0, y=0, width=0, height=0, **kwargs):
        shape = Shape(name, kind, x, y, width, height, **kwargs)
        self.shapes.append(shape)
        return name

    def box(self, name, x, y, width, height, fill="#FFFFFF", stroke=GREY, parent="1", dashed=False):
        return self.add("box", name, x, y, width, height, fill=fill, stroke=stroke, parent=parent, dashed=dashed)

    def label(self, name, x, y, lines, size=16, color=TEXT, bold=False, parent="1", width=500):
        lines = (lines,) if isinstance(lines, str) else tuple(lines)
        return self.add("text", name, x, y, width, len(lines) * (size + 6),
                        text=lines, size=size, color=color, bold=bold, parent=parent)

    def icon(self, name, asset, x, y, size=42, parent="1"):
        return self.add("image", name, x, y, size, size, asset=asset, parent=parent)

    def path(self, name, points, color=BLUE, dashed=False, arrow=True, thickness=2.5):
        return self.add("path", name, color=color, points=points, dashed=dashed, arrow=arrow, thickness=thickness)

    def fault(self, name, x, y):
        self.path(name + "-a", [(x - 12, y - 12), (x + 12, y + 12)], RED, arrow=False, thickness=5)
        self.path(name + "-b", [(x - 12, y + 12), (x + 12, y - 12)], RED, arrow=False, thickness=5)


def region(scene, name, x, width, title, subtitle):
    scene.box(name, x, 110, width, 800, fill="#F3F2F1", dashed=True)
    scene.label(name + "-title", x + 20, 124, title, 21, bold=True, parent=name, width=width - 40)
    scene.label(name + "-subtitle", x + 20, 151, subtitle, 14, "#605E5C", parent=name, width=width - 40)


def hub(scene, east):
    name = "east" if east else "west"
    x = 500 if east else 1215
    hub_width = 620 if east else 610
    cidr = "10.10" if east else "10.30"
    parent = name + "-region"
    scene.box(name + "-hub", x, 185, hub_width, 630, stroke=BLUE, parent=parent)
    scene.icon(name + "-vnet-icon", "virtual-network.svg", x + 16, 197, 30, name + "-hub")
    scene.label(name + "-hub-title", x + 60, 201, f"{name.title()} hub VNet - {cidr}.0.0/16",
                19, bold=True, parent=name + "-hub", width=hub_width - 70)
    inner_x, inner_width = x + 25, hub_width - 50
    scene.box(name + "-dns-group", inner_x, 245, inner_width, 350, stroke="#B3D6F2", parent=name + "-hub")
    scene.icon(name + "-resolver-icon", "dns-private-resolver.svg", inner_x + 18, 258, 42, name + "-dns-group")
    scene.label(name + "-resolver-title", inner_x + 76, 261,
                [f"{name.title()} DNS Private Resolver", "+ attached regional forwarding ruleset"],
                17, bold=True, parent=name + "-dns-group", width=inner_width - 85)
    inbound_x, outbound_x = inner_x + 20, inner_x + 290
    scene.box(name + "-inbound", inbound_x, 325, 235, 78, fill="#F5FAFF", dashed=True, parent=name + "-dns-group")
    scene.label(name + "-inbound-label", inbound_x + 10, 335,
                ["Inbound endpoint", cidr + ".0.4", "Dedicated subnet: " + cidr + ".0.0/28"],
                14, parent=name + "-inbound", width=220)
    scene.box(name + "-ruleset", inbound_x, 450, 235, 125, fill="#F7F4FB", stroke=PURPLE, parent=name + "-dns-group")
    scene.label(name + "-ruleset-label", inbound_x + 10, 461,
                [name.title() + " forwarding ruleset", "lab.failover.test.", "  -> " + cidr + ".2.4:53",
                 "Links: spoke + hub" if east else "Link: West hub only"],
                14, parent=name + "-ruleset", width=220)
    scene.box(name + "-outbound", outbound_x, 450, 260 if east else 250, 125,
              fill="#F5FAFF", dashed=True, parent=name + "-dns-group")
    scene.label(name + "-outbound-label", outbound_x + 12, 462,
                ["Outbound endpoint", "Subnet: " + cidr + ".1.0/28", "Sends forwarded DNS", "to this region's upstream"],
                14, parent=name + "-outbound", width=230)
    scene.path(name + "-ruleset-to-outbound", [(inbound_x + 235, 512), (outbound_x, 512)], BLUE)
    if not east:
        scene.path("west-inbound-to-ruleset", [(inbound_x + 117, 403), (inbound_x + 117, 450)], BLUE)
    else:
        scene.label("east-inbound-note", inbound_x + 4, 410, "Not the workload's primary DNS", 13, "#605E5C",
                    parent=name + "-dns-group", width=500)
    scene.box(name + "-servers", inner_x, 655, inner_width, 135, fill="#F5FAFF", dashed=True, parent=name + "-hub")
    scene.label(name + "-servers-title", inner_x + 10, 663, "Servers subnet: " + cidr + ".2.0/24",
                13, "#605E5C", parent=name + "-servers", width=inner_width - 20)
    scene.icon(name + "-server-icon", "virtual-machine.svg", inner_x + 22, 700, 48, name + "-servers")
    answer = "192.0.2.10" if east else "192.0.2.20"
    response = (["Fault mode: DROP (A) or SERVFAIL (B)", "Normal answer (not returned): " + answer]
                if east and scene.name == "tc-02-forwarding-failure"
                else ["Test answer: " + answer + "  (TTL 0)"])
    scene.label(name + "-server-label", inner_x + 90, 699,
                [f"{name.title()} custom DNS VM - {cidr}.2.4", "Only upstream target for this regional rule",
                 *response],
                15, parent=name + "-servers", width=inner_width - 100)
    scene.path(name + "-outbound-to-server", [(outbound_x + 125, 575), (outbound_x + 125, 655)], BLUE)


def make_scene(name):
    titles = {
        "architecture-overview": "Architecture overview - Azure DNS primary, West inbound secondary",
        "tc-01-primary-timeout": "TC-01 - Primary DNS timeout at the workload VM",
        "tc-02-forwarding-failure": "TC-02 - Azure DNS reachable, but East forwarding cannot answer",
        "tc-03-peering-removal": "TC-03 - East hub peering removed; linked East DNS path survives",
    }
    scene = Scene(name, titles[name])
    scene.label("title", 32, 24, titles[name], 27, bold=True, width=1820)
    scene.label("subtitle", 32, 65,
                "Both workload VMs stay in East US. Only DNS questions can use the independent West path.",
                17, "#605E5C", width=1820)
    region(scene, "east-region", 30, 1120, "EAST US", "Workload spoke + primary regional forwarding path")
    region(scene, "west-region", 1190, 660, "WEST US", "Independent backup resolver and upstream")

    scene.box("spoke", 55, 185, 380, 300, stroke=BLUE, parent="east-region")
    scene.icon("spoke-vnet-icon", "virtual-network.svg", 70, 198, 30, "spoke")
    scene.label("spoke-title", 110, 201, ["Workload VNet", "10.20.0.0/16"], 17, bold=True, parent="spoke", width=310)
    scene.box("workload-subnet", 75, 258, 340, 100, fill="#F5FAFF", dashed=True, parent="spoke")
    scene.icon("windows-icon", "virtual-machine.svg", 92, 270, 40, "workload-subnet")
    scene.label("windows-label", 143, 274, ["Windows Server", "10.20.0.4"], 13, parent="workload-subnet", width=140)
    scene.icon("ubuntu-icon", "virtual-machine.svg", 268, 270, 40, "workload-subnet")
    scene.label("ubuntu-label", 316, 274, ["Ubuntu", "10.20.0.5"], 13, parent="workload-subnet", width=95)
    scene.label("workload-subnet-label", 88, 332, "Workload subnet: 10.20.0.0/24", 12, "#605E5C",
                parent="workload-subnet", width=320)
    scene.box("client-dns", 75, 378, 340, 87, fill="#EFF6FC", stroke=BLUE, parent="spoke")
    scene.label("client-dns-label", 88, 387,
                ["DNS settings on BOTH workloads", "1. 168.63.129.16  (Azure DNS)", "2. 10.30.0.4  (West inbound)"],
                14, parent="client-dns", width=320)

    scene.box("azure-dns", 65, 565, 340, 115, stroke=BLUE, parent="east-region")
    scene.icon("azure-dns-icon", "azure-dns.svg", 82, 587, 45, "azure-dns")
    scene.label("azure-dns-label", 143, 579,
                ["Azure DNS", "168.63.129.16", "East spoke VNet context"],
                17, parent="azure-dns", width=250)
    scene.box("platform-explanation", 65, 718, 340, 88, fill="#FAFAFA", stroke="#D2D0CE", parent="east-region")
    scene.label("platform-explanation-label", 78, 728,
                ["Platform service, not a hub DNS VM.", "Ruleset link is NOT a peering route.",
                 "East inbound is not the primary."],
                13, "#605E5C", parent="platform-explanation", width=320)

    hub(scene, east=True)
    hub(scene, east=False)

    scene.path("primary-client-request", [(245, 465), (245, 565)], BLUE, thickness=3)
    scene.label("primary-label", 68, 484 if name == "tc-01-primary-timeout" else 504,
                ["Primary DNS", "request"], 14, BLUE, width=165)
    scene.path("east-service-link", [(405, 622), (475, 622), (475, 512), (545, 512)],
               PURPLE, dashed=True, thickness=2.5)
    scene.path("east-peering", [(435, 270), (500, 270)], GREY, dashed=True, arrow=False, thickness=2)
    scene.label("east-peering-label", 442, 223, ["East hub", "peering"], 11, "#605E5C", width=70)

    active_backup = name in ("tc-01-primary-timeout", "tc-02-forwarding-failure")
    backup_color = GREEN if active_backup else ORANGE
    scene.path("west-backup", [(415, 422), (455, 422), (455, 850), (1165, 850), (1165, 364), (1260, 364)],
               backup_color, dashed=not active_backup, thickness=3)
    scene.box("west-route-caption-bg", 620, 830, 455, 45, stroke="none")
    scene.label("west-route-caption", 633, 833,
                ["Direct global VNet peering: East spoke <-> West hub",
                 "Backup DNS target: 10.30.0.4"],
                14, backup_color, bold=active_backup, width=460)

    if name == "tc-01-primary-timeout":
        scene.fault("primary-dropped", 245, 531)
        scene.box("fault-label-bg", 62, 524, 169, 35, fill="#FFF1F0", stroke="none")
        scene.label("fault-label", 68, 529, "Drop client DNS :53", 13, RED, bold=True, width=165)
    elif name == "tc-02-forwarding-failure":
        scene.fault("upstream-fault", 940, 617)
        scene.label("fault-label", 536, 607,
                    ["A: drop DNS from East outbound subnet", "OR B: reachable East upstream returns SERVFAIL"],
                    13, RED, bold=True, width=390)
    elif name == "tc-03-peering-removal":
        scene.fault("east-peer-removed", 467, 270)
        scene.label("east-peer-removed-note", 70, 833,
                    ["Only East spoke/hub peering is removed.",
                     "The ruleset link and West peering remain."],
                    13, RED, bold=True, width=360)

    scene.box("legend", 30, 935, 1820, 92, fill="#FFFFFF", stroke="#B3B0AD")
    scene.label("legend-title", 48, 947, "HOW TO READ THE DRAWING", 14, bold=True, width=400)
    for index, (color, dashed, label) in enumerate([
        (BLUE, False, "DNS request / processing"),
        (PURPLE, True, "Ruleset service association"),
        (backup_color, not active_backup, "West path: active" if active_backup else "West path: available standby"),
        (GREY, True, "Separate peering relationship"),
    ]):
        x = 48 + index * 450
        scene.path(f"legend-line-{index}", [(x, 990), (x + 48, 990)], color, dashed=dashed, arrow=False)
        scene.label(f"legend-label-{index}", x + 60, 978, label, 14, color, width=375)

    notes = {
        "architecture-overview": [
            "Normal lookup: Azure DNS -> East linked ruleset -> East outbound -> East custom DNS.",
            "Backup lookup, if selected by the OS: West inbound -> West ruleset -> West outbound -> West custom DNS.",
            "East answer = 192.0.2.10; West answer = 192.0.2.20. These are identifying test values, not application endpoints.",
            "No hub-to-hub peering, NVAs, or on-premises sites are part of this lab. See the scenario pages for scoped faults.",
        ],
        "tc-01-primary-timeout": [
            "FAULT: workload firewall drops UDP and TCP DNS (:53) to 168.63.129.16. Azure DNS itself is not shut down.",
            "OBSERVED: first successful West lookup = Windows 1.088 s; Ubuntu 10.082 s. West answered 15/15 calls per OS.",
            "The OS selects the secondary; the application has no retry loop. Only DNS is blocked, not all Azure platform traffic.",
            "After restoration: Windows's three immediate probes used East; Ubuntu's three stayed on West. Failback is not instant.",
        ],
        "tc-02-forwarding-failure": [
            "FAULT A: drop East-outbound-subnet DNS at upstream firewall. First West lookup: Windows 1.105 s; Ubuntu 5.079 s.",
            "FAULT B (separate run): reachable East upstream returns SERVFAIL. Windows 1.109 s; Ubuntu 5.075 s.",
            "Each variant: 15/15 West answers per OS; zero native lookup failures. Primary Azure DNS remains reachable.",
            "IMPORTANT: West requests preceded Azure's SERVFAIL response. These Azure-path tests prove timeout-driven fallback.",
        ],
        "tc-03-peering-removal": [
            "FAULT: remove both directions of East workload/hub peering. Do NOT remove the East forwarding-ruleset link.",
            "OBSERVED: 15/15 East answers per OS; zero native failures. Median lookup: Windows 9.8 ms; Ubuntu 9.9 ms.",
            "Direct queries to East inbound timed out as expected. Native Azure DNS resolution uses a different, linked service path.",
            "East outbound and its upstream stay in the same hub. All four directional East/West peerings were restored afterward.",
        ],
    }
    scene.box("measurement-note", 30, 1050, 1820, 145, fill="#F5FAFF", stroke=BLUE)
    scene.label("measurement-note-text", 48, 1065, notes[name], 16, width=1780)
    scene.label("measurement-scope", 48, 1173,
                "Timing scope: native DNS lookup duration, not fault-to-recovery time or application availability. "
                "15 native lookups per OS per main test variant.",
                12, "#605E5C", width=1780)
    return scene


def image_data(asset, browser=True):
    encoded = base64.b64encode((HERE / "assets" / asset).read_bytes()).decode("ascii")
    return ("data:image/svg+xml;base64," if browser else "data:image/svg+xml,") + encoded


def svg(scene):
    markers = "".join(
        f'<marker id="arrow-{color[1:]}" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto">'
        f'<path d="M0,0 L0,6 L8,3 z" fill="{color}"/></marker>'
        for color in (BLUE, PURPLE, GREEN, ORANGE, RED, GREY))
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" style="max-width:100%;height:auto" role="img" aria-labelledby="title desc">',
        f"<title id=\"title\">{escape(scene.title)}</title>",
        "<desc id=\"desc\">East workload clients use Azure DNS as primary and West inbound as secondary. "
        "Regional containers, endpoint subnets, ruleset links and scoped fault locations are shown.</desc>",
        f"<defs>{markers}</defs>", '<rect width="100%" height="100%" fill="#FFFFFF"/>',
        '<g font-family="Segoe UI,Arial,sans-serif">',
    ]
    for shape in scene.shapes:
        if shape.kind == "box":
            dash = ' stroke-dasharray="7 5"' if shape.dashed else ""
            out.append(f'<rect id="{shape.name}" x="{shape.x}" y="{shape.y}" width="{shape.width}" height="{shape.height}" '
                       f'rx="6" fill="{shape.fill}" stroke="{shape.stroke}" stroke-width="{shape.thickness}"{dash}/>')
        elif shape.kind == "text":
            weight = "700" if shape.bold else "400"
            lines = "".join(f'<tspan x="{shape.x}" y="{shape.y + shape.size + i * (shape.size + 6)}">{escape(line)}</tspan>'
                            for i, line in enumerate(shape.text))
            out.append(f'<text id="{shape.name}" fill="{shape.color}" font-size="{shape.size}" font-weight="{weight}">{lines}</text>')
        elif shape.kind == "image":
            out.append(f'<image id="{shape.name}" x="{shape.x}" y="{shape.y}" width="{shape.width}" height="{shape.height}" '
                       f'preserveAspectRatio="xMidYMid meet" href="{image_data(shape.asset)}"/>')
        elif shape.kind == "path":
            points = " ".join(f"{x},{y}" for x, y in shape.points)
            dash = ' stroke-dasharray="8 5"' if shape.dashed else ""
            marker = f' marker-end="url(#arrow-{shape.color[1:]})"' if shape.arrow else ""
            out.append(f'<polyline id="{shape.name}" points="{points}" fill="none" stroke="{shape.color}" '
                       f'stroke-width="{shape.thickness}" stroke-linejoin="round"{dash}{marker}/>')
    return "\n".join(out + ["</g></svg>"])


def drawio_page(scene):
    diagram = ET.Element("diagram", {"id": scene.name, "name": scene.title})
    model = ET.SubElement(diagram, "mxGraphModel", {
        "dx": str(WIDTH), "dy": str(HEIGHT), "grid": "1", "gridSize": "10", "guides": "1",
        "connect": "1", "arrows": "1", "page": "1", "pageScale": "1",
        "pageWidth": str(WIDTH), "pageHeight": str(HEIGHT), "background": "#FFFFFF"})
    root = ET.SubElement(model, "root")
    ET.SubElement(root, "mxCell", {"id": "0"})
    ET.SubElement(root, "mxCell", {"id": "1", "parent": "0"})
    shapes = {shape.name: shape for shape in scene.shapes}
    for shape in scene.shapes:
        common = "fontFamily=Segoe UI;html=1;whiteSpace=wrap;"
        attributes = {"id": shape.name, "parent": shape.parent}
        if shape.kind == "path":
            diagonal = (len(shape.points) == 2 and shape.points[0][0] != shape.points[1][0]
                        and shape.points[0][1] != shape.points[1][1])
            attributes.update(edge="1", parent="1", style=common +
                              f"edgeStyle={'none' if diagonal else 'orthogonalEdgeStyle'};rounded=0;strokeColor={shape.color};"
                              f"strokeWidth={shape.thickness};endArrow={'block' if shape.arrow else 'none'};"
                              f"endFill=1;dashed={int(shape.dashed)};")
            cell = ET.SubElement(root, "mxCell", attributes)
            geometry = ET.SubElement(cell, "mxGeometry", {"relative": "1", "as": "geometry"})
            for label, point in (("sourcePoint", shape.points[0]), ("targetPoint", shape.points[-1])):
                ET.SubElement(geometry, "mxPoint", {"x": str(point[0]), "y": str(point[1]), "as": label})
            if len(shape.points) > 2:
                array = ET.SubElement(geometry, "Array", {"as": "points"})
                for x, y in shape.points[1:-1]:
                    ET.SubElement(array, "mxPoint", {"x": str(x), "y": str(y)})
            continue
        attributes["vertex"] = "1"
        if shape.kind == "box":
            attributes["style"] = common + (
                f"rounded=1;arcSize=3;container=1;collapsible=0;fillColor={shape.fill};"
                f"strokeColor={shape.stroke};strokeWidth={shape.thickness};dashed={int(shape.dashed)};")
        elif shape.kind == "text":
            attributes["value"] = "<br>".join(escape(line) for line in shape.text)
            attributes["style"] = common + (
                f"text;align=left;verticalAlign=top;spacing=0;fontSize={shape.size};"
                f"fontColor={shape.color};fontStyle={int(shape.bold)};")
        elif shape.kind == "image":
            attributes["style"] = common + "shape=image;aspect=fixed;imageAspect=1;image=" + image_data(shape.asset, False) + ";"
        cell = ET.SubElement(root, "mxCell", attributes)
        parent = shapes.get(shape.parent)
        ET.SubElement(cell, "mxGeometry", {
            "x": str(shape.x - parent.x if parent else shape.x),
            "y": str(shape.y - parent.y if parent else shape.y),
            "width": str(shape.width), "height": str(shape.height), "as": "geometry"})
    return diagram


def main():
    scenes = [make_scene(name) for name in (
        "architecture-overview", "tc-01-primary-timeout",
        "tc-02-forwarding-failure", "tc-03-peering-removal")]
    document = ET.Element("mxfile", {"host": "app.diagrams.net", "type": "device", "pages": str(len(scenes))})
    for scene in scenes:
        document.append(drawio_page(scene))
        content = svg(scene)
        ET.fromstring(content)
        (HERE / (scene.name + ".svg")).write_text(content, encoding="utf-8", newline="\n")
    ET.indent(document)
    ET.ElementTree(document).write(HERE / "dns-failover-scenarios.drawio", encoding="utf-8", xml_declaration=True)
    (HERE.parent.parent / "architecture.svg").write_text(svg(scenes[0]), encoding="utf-8", newline="\n")
    print(f"Generated {len(scenes)} SVGs and {len(scenes)} editable draw.io pages in {HERE}")


if __name__ == "__main__":
    main()
