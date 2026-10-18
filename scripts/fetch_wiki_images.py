#!/usr/bin/env python3
"""Fetch Wikipedia lead images for the real-world figures and save them as
data-URIs in data/wiki_images.json. build_data.py picks these up if present.

Run this where outbound access to Wikimedia is allowed (this project's default
sandbox blocks it). No third-party deps — stdlib only.
"""
import json, base64, urllib.request, urllib.parse, os

TITLES = {
 "Alexander von Humboldt":"Alexander_von_Humboldt",
 "Ignacio Manuel Altamirano":"Ignacio_Manuel_Altamirano",
 "Antonieta Rivas Mercado":"Antonieta_Rivas_Mercado",
 "Bartolomé de las Casas":"Bartolomé_de_las_Casas",
 "Carlos Finaly":"Carlos_Finlay",
 "Carlos Fuentes":"Carlos_Fuentes",
 "Cervantes":"Miguel_de_Cervantes",
}
UA = {"User-Agent":"AmparacanWiki/1.0 (worldbuilding project)"}

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=25)

out = {}
for name, title in TITLES.items():
    try:
        api = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title, safe="")
        s = json.load(get(api))
        src = (s.get("thumbnail") or {}).get("source") or (s.get("originalimage") or {}).get("source")
        if not src:
            print("no image:", name); continue
        raw = get(src).read()
        low = src.lower()
        mime = "png" if low.endswith(".png") else ("svg+xml" if low.endswith(".svg") else "jpeg")
        out[name] = f"data:image/{mime};base64," + base64.b64encode(raw).decode()
        print("ok:", name, f"{len(raw)//1024} KB")
    except Exception as e:
        print("fail:", name, e)

os.makedirs("data", exist_ok=True)
json.dump(out, open("data/wiki_images.json", "w"))
print("saved", len(out), "images -> data/wiki_images.json")
