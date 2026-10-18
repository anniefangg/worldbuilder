#!/usr/bin/env python3
"""Inject the dataset into the template and write the deployable HTML.

Writes wiki.html (published to the Claude Artifact) and index.html (served by
Vercel) — identical content. Run after build_data.py.
"""
import json
tpl = open("/home/user/worldbuilder/wiki_template.html").read()
obj = json.loads(open("/home/user/worldbuilder/data/wiki_data.json").read())
obj["revisions"] = []
data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
html = tpl.replace("__WIKI_DATA__", data)
for path in ("/home/user/worldbuilder/wiki.html", "/home/user/worldbuilder/index.html"):
    open(path, "w").write(html)
print("built wiki.html + index.html —", round(len(html)/1024), "KB")
