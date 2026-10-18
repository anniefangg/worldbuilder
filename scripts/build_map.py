"""Build the 3D map artifact: (re)parse the .ai if needed, then inject the data into
map_template.html → map.html (published as an Artifact).

Usage: python3 scripts/build_map.py [--reparse] [--preview DIR]
  --reparse      re-run scripts/parse_ai_map.py even if data/map/map_data.json exists
  --preview DIR  also write DIR/index.html wrapped in a doctype for local preview
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "map", "map_data.json")

if "--reparse" in sys.argv or not os.path.exists(DATA):
    subprocess.check_call([sys.executable, os.path.join(ROOT, "scripts", "parse_ai_map.py")], cwd=ROOT)

tpl = open(os.path.join(ROOT, "map_template.html")).read()
data = open(DATA).read().replace("<", "\\u003c")
html = tpl.replace("__MAP_DATA__", data)
open(os.path.join(ROOT, "map.html"), "w").write(html)
print("wrote map.html (%.2f MB)" % (len(html.encode()) / 1e6))

if "--preview" in sys.argv:
    d = sys.argv[sys.argv.index("--preview") + 1]
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "index.html"), "w").write(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head><body>'
        + html + "</body></html>")
    print("wrote preview", os.path.join(d, "index.html"))
