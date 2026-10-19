"""Build the 3D map artifact: (re)parse the .ai if needed, then inject the data into
map_template.html → map.html (published as an Artifact).

Usage: python3 scripts/build_map.py [--source FILE.ai] [--reparse] [--preview DIR]
  --source FILE  re-import an updated Illustrator file (copied to data/map/ and parsed);
                 building ids are matched to the previous build so 3D edits stay attached
  --reparse      re-run scripts/parse_ai_map.py even if data/map/map_data.json exists
  --preview DIR  also write DIR/index.html wrapped in a doctype for local preview
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "map", "map_data.json")

import shutil

src = os.path.join(ROOT, "data", "map", "reorganise15.ai")
if "--source" in sys.argv:
    given = sys.argv[sys.argv.index("--source") + 1]
    src = os.path.join(ROOT, "data", "map", os.path.basename(given))
    if os.path.abspath(given) != src:
        shutil.copyfile(given, src)
if "--source" in sys.argv or "--reparse" in sys.argv or not os.path.exists(DATA):
    subprocess.check_call([sys.executable, os.path.join(ROOT, "scripts", "parse_ai_map.py"), src, DATA], cwd=ROOT)

tpl = open(os.path.join(ROOT, "map_template.html")).read()
data = open(DATA).read().replace("<", "\\u003c")
import base64
char = base64.b64encode(open(os.path.join(ROOT, "data", "character", "barbossa.glb"), "rb").read()).decode() if os.path.exists(os.path.join(ROOT, "data", "character", "barbossa.glb")) else ""
html = tpl.replace("__MAP_DATA__", data).replace("__CHAR_GLB__", char)
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
