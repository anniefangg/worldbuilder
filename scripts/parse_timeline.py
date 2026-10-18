#!/usr/bin/env python3
"""Parse the Chronology sheet (year | event markdown table) into JSON events."""
import json, re, sys
SRC = sys.argv[1]
OUT = sys.argv[2] if len(sys.argv) > 2 else "/home/user/worldbuilder/data/timeline_raw.json"
raw = json.load(open(SRC))["fileContent"]

def cells(line):
    p = line.split("|")
    if p and p[0].strip() == "": p = p[1:]
    if p and p[-1].strip() == "": p = p[:-1]
    return [c.strip() for c in p]

# The sheet holds several draft tables. The chronology is spread across the
# 2-column blocks; wider tables are other data. Take every genuine 2-column
# year row, drop exact duplicates, then collapse reworded near-duplicates
# (same year + shared opening) keeping the more detailed wording.
lines = [l for l in raw.splitlines() if l.strip().startswith("|")]
rows = []
seen = set()
def clean(x):
    x = x.replace("\\", "").strip()
    x = re.sub(r"^\[merged\]\s*", "", x).strip()   # unwrap merged-cell markers
    return x
for line in lines:
    c = cells(line)
    if not c: continue
    yr = c[0]
    m = re.search(r"\d{3,4}", yr)                               # first cell must carry a year
    if not m: continue
    year_num = int(m.group(0))
    if not (700 <= year_num <= 2100): continue
    txt = ""                                                    # event text = first real cell after the year
    for x in c[1:]:
        xx = clean(x)
        if xx and not re.fullmatch(r"[~\d\s.\-]+", xx) and len(xx) > 3:
            txt = xx; break
    if not txt or txt.lower() in ("event","description","note"): continue
    key = (year_num, txt.lower())
    if key in seen: continue
    seen.add(key)
    rows.append({"y": year_num, "label": yr.replace("\\", "").strip(), "text": txt,
                 "approx": ("~" in yr) or ("c." in yr.lower())})

# collapse near-duplicates: within a year, if two texts share their first 18
# normalised chars, keep the longer (more detailed) one.
def pref(s): return re.sub(r"[^a-z0-9 ]","",s.lower())[:18]
rows.sort(key=lambda e: (e["y"], -len(e["text"])))
events = []
byyear = {}
for e in rows:
    p = pref(e["text"])
    if any(pref(x["text"]) == p for x in byyear.get(e["y"], [])):
        continue                                               # a longer variant already kept
    byyear.setdefault(e["y"], []).append(e)
    events.append(e)

events.sort(key=lambda e: (e["y"], e["label"]))
json.dump(events, open(OUT, "w"), ensure_ascii=False)
print("events:", len(events))
print("range:", events[0]["label"], "→", events[-1]["label"])
from collections import Counter
cent = Counter((e["y"]//100)*100 for e in events)
print("by century:", dict(sorted(cent.items())))
print("samples:", [f'{e["label"]}: {e["text"][:50]}' for e in events[:3]])
