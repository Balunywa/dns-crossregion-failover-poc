"""Check evidence completeness independently of whether failover succeeds."""

import argparse

import json

from pathlib import Path



from analyze import analyze





def validate(folder):

    summary = analyze(folder)

    manifest = json.loads((folder / "manifest.json").read_text())

    errors = []

    expected = {(client, phase) for client in ("dnspoc-win", "dnspoc-ubuntu") for phase in manifest["phases"]}

    actual = set()

    upstream = []

    for path in (folder / "extracted").glob("dnspoc-up-*-logs/upstream.jsonl"):

        upstream.extend(json.loads(line) for line in path.read_text().splitlines() if line.strip())

    lookup = {}

    for entry in upstream:

        if "name" in entry:

            lookup.setdefault(entry["name"], []).append(entry)

    for row in summary["results"]:

        phase = row["phase"]

        client = row["clientPhase"][:-(len(phase) + 1)]

        actual.add((client, phase))

        if row["calls"] != 15:

            errors.append(f"{client}/{phase}: expected 15 native calls, got {row['calls']}")

        if row["decodeErrors"]:

            errors.append(f"{client}/{phase}: {row['decodeErrors']} packet decode errors")

        details = row["nativeDetails"]

        if len({q["name"] for q in details}) != len(details):

            errors.append(f"{client}/{phase}: duplicate native query names")

        for q in details:

            records = lookup.get(q["name"].lower(), [])

            if q["success"]:

                if not q["wirePrimaryRequests"] and not q["wireWestRequests"]:

                    errors.append(f"{client}/{phase}: successful query has no emitted DNS request: {q['name']}")

                for answer in q.get("answers", []):

                    if not any(e.get("answer") == answer for e in records):

                        errors.append(f"{client}/{phase}: answer not corroborated by upstream log: {q['name']}")

            elif not q.get("error"):

                errors.append(f"{client}/{phase}: failed query has no explicit error")

        if phase in ("east-servfail", "fast-servfail-control"):

            names = {q["name"].lower() for q in details}

            if not any(e.get("name") in names and e.get("mode") == "servfail" and e.get("rcode") == 2 for e in upstream):

                errors.append(f"{client}/{phase}: no upstream SERVFAIL correlated to a native query")

    if actual != expected:

        errors.append(f"Phase coverage differs: missing={expected - actual}, extra={actual - expected}")

    if not (folder / "completed.json").exists():

        errors.append("Harness completion marker is missing")

    result = {"valid": not errors, "errors": errors, "clientPhases": len(actual),

              "nativeCalls": sum(row["calls"] for row in summary["results"]),

              "nativeFailures": sum(row["failures"] for row in summary["results"]),

              "note": "A native query failure is a measured outcome, not by itself an evidence-integrity failure."}

    (folder / "validation.json").write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))

    if errors:

        raise SystemExit(1)

    return result





if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument("evidence", type=Path)

    validate(parser.parse_args().evidence)

