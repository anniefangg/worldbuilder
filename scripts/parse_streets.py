#!/usr/bin/env python3
"""Parse the Streets Google Sheet (markdown-table representation) into clean JSON.

Source: Google Sheet 1ku27nVZ09fvMfnJmylsoNam53DqO6d-RiNhl9ILdIg8
The Drive MCP connector renders the sheet as pipe-delimited markdown tables.
Row layout: | type_abbrev | type_full | (count) | street_name | neighbourhoods | category | meaning | note |
"""
import json, re, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else \
    "/root/.claude/projects/-home-user-worldbuilder/92568b5a-8cb8-5165-a089-1f13ff25dc32/tool-results/mcp-Google_Drive-read_file_content-1787498596128.txt"
OUT = sys.argv[2] if len(sys.argv) > 2 else "/home/user/worldbuilder/data/streets.json"

raw = json.load(open(SRC))["fileContent"]

def cells(line):
    # split a markdown table row into trimmed cell values
    parts = line.split("|")
    # drop leading/trailing empties produced by the outer pipes
    if parts and parts[0].strip() == "": parts = parts[1:]
    if parts and parts[-1].strip() == "": parts = parts[:-1]
    return [c.strip() for c in parts]

lines = raw.splitlines()
# The real named-streets table is the first table only; later tables are
# category-count planning grids. Cut at the second separator row.
seps = [i for i, l in enumerate(lines) if ":-" in l and l.strip().startswith("|")]
end = seps[1] if len(seps) > 1 else len(lines)
lines = lines[:end]

streets = []
seen = set()
for line in lines:
    if not line.strip().startswith("|"):
        continue
    c = cells(line)
    if len(c) < 7:
        continue
    if set("".join(c).replace("-", "").replace(":", "")) <= set(" "):  # separator row
        continue
    type_abbrev, type_full, _count, name = c[0], c[1], c[2], c[3]
    neigh, category, meaning = c[4], c[5], c[6]
    note = c[7] if len(c) > 7 else ""
    # skip header / non-data rows
    if name in ("", "Street name") or type_full in ("Type of street",):
        continue
    if name.startswith("[merged]") or "Calle, Avenida" in type_full:
        continue
    # must look like a real street entry: has a full type word
    if not type_full or type_full.lower() in ("calle, avenida, pasaje",):
        continue
    key = name.lower()
    if key in seen:
        continue
    seen.add(key)
    neighbourhoods = [n.strip() for n in re.split(r"[,/]", neigh) if n.strip()]
    streets.append({
        "name": name,
        "type_abbrev": type_abbrev,
        "type_full": type_full,
        "neighbourhoods": neighbourhoods,
        "category": category,
        "meaning": meaning,
        "note": note,
    })

json.dump(streets, open(OUT, "w"), ensure_ascii=False, indent=1)

# diagnostics
from collections import Counter
print("total streets:", len(streets))
print("\ntop types:", Counter(s["type_full"] for s in streets).most_common(12))
print("\ntop categories:", Counter(s["category"] for s in streets).most_common(25))
print("\nsample neighbourhoods:", Counter(n for s in streets for n in s["neighbourhoods"]).most_common(15))
print("\nfirst 3:", json.dumps(streets[:3], ensure_ascii=False))
