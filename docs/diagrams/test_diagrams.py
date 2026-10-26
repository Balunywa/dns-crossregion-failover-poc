import base64
import unittest
import xml.etree.ElementTree as ET

from build_architecture_diagrams import HERE, drawio_page, make_scene, svg

NAMES = (
    "architecture-overview", "tc-01-primary-timeout",
    "tc-02-forwarding-failure", "tc-03-peering-removal",
)
SVG = "{http://www.w3.org/2000/svg}"


class DiagramTests(unittest.TestCase):
    def test_editable_pages_match_generator_and_have_valid_hierarchy(self):
        pages = ET.parse(HERE / "dns-failover-scenarios.drawio").findall("diagram")
        self.assertEqual([page.get("id") for page in pages], list(NAMES))
        for page in pages:
            with self.subTest(page=page.get("id")):
                expected = drawio_page(make_scene(page.get("id")))
                self.assertEqual(
                    ET.canonicalize(ET.tostring(page, encoding="unicode"), strip_text=True),
                    ET.canonicalize(ET.tostring(expected, encoding="unicode"), strip_text=True))
                cells = page.findall(".//mxCell")
                identifiers = [cell.get("id") for cell in cells]
                self.assertEqual(len(set(identifiers)), len(identifiers))
                for cell in cells:
                    if cell.get("parent"):
                        self.assertIn(cell.get("parent"), identifiers)
                self.assertEqual(sum("shape=image" in cell.get("style", "") for cell in cells), 10)
                self.assertTrue(any(cell.get("edge") == "1" for cell in cells))

    def test_vector_exports_are_current_and_icons_are_self_contained(self):
        for name in NAMES:
            with self.subTest(page=name):
                scene = make_scene(name)
                content = (HERE / (name + ".svg")).read_text(encoding="utf-8")
                self.assertEqual(content, svg(scene))
                root = ET.fromstring(content)
                images = root.findall(f".//{SVG}image")
                assets = {shape.name: shape.asset for shape in scene.shapes if shape.kind == "image"}
                self.assertEqual(len(images), 10)
                for image in images:
                    uri = image.get("href")
                    self.assertTrue(uri.startswith("data:image/svg+xml;base64,"))
                    self.assertEqual(base64.b64decode(uri.split(",", 1)[1]),
                                     (HERE / "assets" / assets[image.get("id")]).read_bytes())
        self.assertEqual((HERE.parent.parent / "architecture.svg").read_bytes(),
                         (HERE / "architecture-overview.svg").read_bytes())

    def test_scenario_faults_are_isolated_and_caveats_remain_visible(self):
        expected_faults = (
            set(), {"primary-dropped-a", "primary-dropped-b"},
            {"upstream-fault-a", "upstream-fault-b"},
            {"east-peer-removed-a", "east-peer-removed-b"},
        )
        for name, expected in zip(NAMES, expected_faults):
            scene = make_scene(name)
            actual = {shape.name for shape in scene.shapes
                      if shape.kind == "path" and shape.color == "#C4262E"}
            self.assertEqual(actual, expected)
            identifiers = {shape.name for shape in scene.shapes}
            self.assertTrue({"east-service-link", "west-backup", "measurement-scope"} <= identifiers)
        content = svg(make_scene("tc-02-forwarding-failure"))
        self.assertIn("West requests preceded Azure", content)
        self.assertIn("Fault mode: DROP (A) or SERVFAIL (B)", content)


if __name__ == "__main__":
    unittest.main()
