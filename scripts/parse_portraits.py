#!/usr/bin/env python3
"""Extract portraits from an exported Characters xlsx and map each to a person.

Floating images are anchored to a cell (col,row); the person's name is the
text in the header cell above the portrait (same column, nearest non-empty
row above). Emits data/portraits.json: {name: "data:image/...;base64,..."}.
"""
import os, re, sys, json, base64, zipfile
import xml.etree.ElementTree as ET

XLSX = sys.argv[1]
OUT  = sys.argv[2] if len(sys.argv) > 2 else "/home/user/worldbuilder/data/portraits.json"
D = "/tmp/xlsx"

NS = {
 'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
 'xdr':'http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing',
 'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
 'rel':'http://schemas.openxmlformats.org/package/2006/relationships',
}

# shared strings
def load_shared():
    p=os.path.join(D,'xl/sharedStrings.xml')
    if not os.path.exists(p):return []
    root=ET.parse(p).getroot()
    out=[]
    for si in root.findall('x:si',NS):
        out.append(''.join(t.text or '' for t in si.iter('{%s}t'%NS['x'])))
    return out
SHARED=load_shared()

def col_to_idx(col):  # 'A'->0
    n=0
    for ch in col: n=n*26+(ord(ch)-64)
    return n-1

# cell text map {(col,row0): text}
def load_cells():
    root=ET.parse(os.path.join(D,'xl/worksheets/sheet1.xml')).getroot()
    cells={}
    for c in root.iter('{%s}c'%NS['x']):
        ref=c.get('r');
        if not ref:continue
        m=re.match(r'([A-Z]+)(\d+)',ref); col=col_to_idx(m.group(1)); row=int(m.group(2))-1
        t=c.get('t'); v=c.find('x:v',NS); isv=c.find('x:is',NS)
        val=''
        if t=='s' and v is not None: val=SHARED[int(v.text)]
        elif t=='inlineStr' and isv is not None: val=''.join(x.text or '' for x in isv.iter('{%s}t'%NS['x']))
        elif v is not None: val=v.text or ''
        val=(val or '').strip()
        if val: cells[(col,row)]=val
    return cells
CELLS=load_cells()

# drawing rels: rId -> media path
def load_drawrels():
    root=ET.parse(os.path.join(D,'xl/drawings/_rels/drawing1.xml.rels')).getroot()
    return {r.get('Id'):os.path.basename(r.get('Target')) for r in root}
DRAWRELS=load_drawrels()

# anchors: for each pic, (col,row,embed)
def load_anchors():
    root=ET.parse(os.path.join(D,'xl/drawings/drawing1.xml')).getroot()
    out=[]
    for anch in list(root):
        frm=anch.find('xdr:from',NS)
        if frm is None:continue
        col=int(frm.find('xdr:col',NS).text); row=int(frm.find('xdr:row',NS).text)
        blip=anch.find('.//a:blip',{'a':'http://schemas.openxmlformats.org/drawingml/2006/main'})
        embed=blip.get('{%s}embed'%NS['r']) if blip is not None else None
        if embed: out.append((col,row,embed))
    return out
ANCHORS=load_anchors()

def name_for(col,row):
    # nearest non-empty cell above (or at) the anchor in the same column
    for rr in range(row,-1,-1):
        if (col,rr) in CELLS:
            v=CELLS[(col,rr)]
            if v and v!='[merged]' and not v.startswith('[merged]'):
                return v
    return None

mapping={}
report=[]
for col,row,embed in ANCHORS:
    media=DRAWRELS.get(embed)
    nm=name_for(col,row)
    report.append((col,row,media,nm))
    if row>=100:  # rows 110/139 are ship grids, not people
        continue
    if not nm or not media:continue
    path=os.path.join(D,'xl/media',media)
    if not os.path.exists(path):continue
    ext=os.path.splitext(media)[1].lower().lstrip('.')
    mime='jpeg' if ext in ('jpg','jpeg') else 'png'
    b=base64.b64encode(open(path,'rb').read()).decode()
    # keep the first image seen per name
    if nm not in mapping:
        mapping[nm]=f"data:image/{mime};base64,{b}"

json.dump(mapping,open(OUT,'w'))
print(f"anchors: {len(ANCHORS)}  mapped: {len(mapping)}")
print("\ncol,row -> media -> name")
for col,row,media,nm in sorted(report):
    print(f"  c{col} r{row}  {media:14} -> {nm}")
