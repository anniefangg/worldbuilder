#!/usr/bin/env python3
"""Convert a 3D-map building export into data/map/building_attrs.json.

Input: a raw ArtifactData list dump of the map artifact's `buildings`
collection — a JSON array of {"id": bId, "data": {name, address, tags[],
history, details, attrs:{k:v}, style:{...}, updatedAt}}. (A top-level object
with a "docs"/"documents"/"items" array is accepted too.)
Output: {bId: data}, which scripts/build_data.py turns into building pages.

usage: python3 scripts/sync_map_buildings.py path/to/dump.json [out.json]
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if len(sys.argv) < 2:
    sys.exit(__doc__.strip().splitlines()[-1])
src = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "data/map/building_attrs.json")

dump = json.load(open(src))
if isinstance(dump, dict):
    for k in ("docs", "documents", "items", "results"):
        if isinstance(dump.get(k), list):
            dump = dump[k]; break
if not isinstance(dump, list):
    sys.exit("expected a JSON array of {id, data} records")

attrs = {}
for row in dump:
    bid, data = row.get("id"), row.get("data")
    if bid and isinstance(data, dict):
        attrs[bid] = data
attrs = dict(sorted(attrs.items()))

os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    json.dump(attrs, f, ensure_ascii=False, indent=1)
    f.write("\n")
named = sum(1 for d in attrs.values() if (d.get("name") or "").strip())
print(f"wrote {len(attrs)} buildings ({named} named) -> {out}")
