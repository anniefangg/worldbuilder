#!/usr/bin/env python3
"""Extract portraits from a multi-tab Characters xlsx export.

Walks every worksheet, follows each sheet's drawing to its anchored images,
and maps each image to the person named in the nearest non-empty header cell
above it (same column). Prints a per-sheet review report and writes
data/portraits_candidates.json = {name: {uri, sheet, row, media}}.
"""
import os, re, sys, json, base64, zipfile, shutil
import xml.etree.ElementTree as ET

XLSX = sys.argv[1]
D    = sys.argv[2] if len(sys.argv) > 2 else "/tmp/xlsx_all"
OUT  = "/home/user/worldbuilder/data/portraits_candidates.json"

if os.path.isdir(D): shutil.rmtree(D)
os.makedirs(D)
with zipfile.ZipFile(XLSX) as z: z.extractall(D)

A='http://schemas.openxmlformats.org/drawingml/2006/main'
NS={'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'xdr':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

def shared():
    p=os.path.join(D,'xl/sharedStrings.xml')
    if not os.path.exists(p):return []
    root=ET.parse(p).getroot()
    return [''.join(t.text or '' for t in si.iter('{%s}t'%NS['x'])) for si in root.findall('x:si',NS)]
SHARED=shared()

def col_idx(c):
    n=0
    for ch in c:n=n*26+(ord(ch)-64)
    return n-1

def sheet_names():  # r:id -> display name, in workbook order
    wb=ET.parse(os.path.join(D,'xl/workbook.xml')).getroot()
    rels=ET.parse(os.path.join(D,'xl/_rels/workbook.xml.rels')).getroot()
    rid_to_target={r.get('Id'):os.path.basename(r.get('Target')) for r in rels}
    out=[]
    for s in wb.find('x:sheets',NS):
        rid=s.get('{%s}id'%NS['r'])
        out.append((s.get('name'), rid_to_target.get(rid)))  # (name, sheetN.xml)
    return out

def cells(sheetfile):
    root=ET.parse(os.path.join(D,'xl/worksheets',sheetfile)).getroot()
    out={}
    for c in root.iter('{%s}c'%NS['x']):
        ref=c.get('r')
        if not ref:continue
        m=re.match(r'([A-Z]+)(\d+)',ref); col=col_idx(m.group(1)); row=int(m.group(2))-1
        t=c.get('t'); v=c.find('x:v',NS); isv=c.find('x:is',NS); val=''
        if t=='s' and v is not None: val=SHARED[int(v.text)]
        elif t=='inlineStr' and isv is not None: val=''.join(x.text or '' for x in isv.iter('{%s}t'%NS['x']))
        elif v is not None: val=v.text or ''
        val=(val or '').strip()
        if val: out[(col,row)]=val
    return out

def sheet_drawing(sheetfile):
    relp=os.path.join(D,'xl/worksheets/_rels',sheetfile+'.rels')
    if not os.path.exists(relp):return None
    for r in ET.parse(relp).getroot():
        if 'drawing' in (r.get('Target') or ''):return os.path.basename(r.get('Target'))
    return None

def drawing_images(drawfile):
    relp=os.path.join(D,'xl/drawings/_rels',drawfile+'.rels')
    rid_media={r.get('Id'):os.path.basename(r.get('Target')) for r in ET.parse(relp).getroot()} if os.path.exists(relp) else {}
    root=ET.parse(os.path.join(D,'xl/drawings',drawfile)).getroot()
    out=[]
    for anch in list(root):
        frm=anch.find('xdr:from',NS)
        if frm is None:continue
        col=int(frm.find('xdr:col',NS).text); row=int(frm.find('xdr:row',NS).text)
        blip=anch.find('.//a:blip',{'a':A})
        embed=blip.get('{%s}embed'%NS['r']) if blip is not None else None
        if embed and embed in rid_media: out.append((col,row,rid_media[embed]))
    return out

def name_above(cellmap,col,row):
    for rr in range(row,-1,-1):
        v=cellmap.get((col,rr))
        if v and not v.startswith('[merged]'):return v
    return None

def datauri(media):
    path=os.path.join(D,'xl/media',media)
    if not os.path.exists(path):return None
    ext=os.path.splitext(media)[1].lower().lstrip('.')
    mime='jpeg' if ext in('jpg','jpeg') else ext
    return f"data:image/{mime};base64,"+base64.b64encode(open(path,'rb').read()).decode()

import unicodedata
def norm(s): return unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower().strip()

SKIP_SHEETS={'Pirate teams'}   # these tabs hold ships/crews, not people
people={}   # normalized name -> record (first occurrence wins)
skipped=[]
for name,sfile in sheet_names():
    dfile=sheet_drawing(sfile)
    if not dfile:continue
    cm=cells(sfile)
    imgs=drawing_images(dfile)
    print(f"\n=== {name} ({sfile} -> {dfile})  images: {len(imgs)} ===")
    for col,row,media in sorted(imgs):
        nm=name_above(cm,col,row)
        is_ship = name in SKIP_SHEETS or row>=100   # ship grids sit far down the pirate tab
        tag='SHIP/skip' if is_ship else 'person'
        print(f"  c{col:<2} r{row:<4} {media:14} -> {nm}   [{tag}]")
        if not nm: continue
        if is_ship: skipped.append(nm); continue
        k=norm(nm)
        if k not in people:
            people[k]={'name':nm,'uri':datauri(media),'sheet':name,'row':row,'media':media}

json.dump(people,open("/home/user/worldbuilder/data/portraits.json"),'w') if False else \
    json.dump(people,open("/home/user/worldbuilder/data/portraits.json","w"))
print(f"\nPEOPLE portraits: {len(people)}   ships skipped: {len(set(map(norm,skipped)))}")
