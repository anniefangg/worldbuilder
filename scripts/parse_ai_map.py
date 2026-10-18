"""Parse the Illustrator map (.ai, PDF-compatible) into per-layer vector features.

Usage:
    python3 scripts/parse_ai_map.py [src.ai] [out.json]   # → data/map/map_data.json
    python3 scripts/parse_ai_map.py [src.ai] --stats      # per-layer colour/width census

No third-party dependencies: the .ai file is a PDF whose single page content
stream holds every layer as an optional-content (/OC) marked section. We inflate
that stream and run a minimal path interpreter (CTM stack, path construction,
paint ops, CMYK/RGB colours). Béziers are flattened to polylines.

Coordinates are returned in artboard points with y pointing up (PDF space);
1pt = 5m in the world.
"""
import base64
import colorsys
import hashlib
import json
import math
import re
import struct
import sys
import zlib

SKIP_LAYERS = {"Scratch - island", "Scratch - buildings", "Labels", "Street names"}

TOKEN = re.compile(
    rb"\((?:\\.|[^\\)])*\)"          # string
    rb"|<<|>>|\[|\]"
    rb"|<[0-9A-Fa-f\s]*>"            # hex string
    rb"|/[^\s/\[\]()<>{}%]+"         # name
    rb"|[-+]?(?:\d+\.?\d*|\.\d+)"     # number
    rb"|[A-Za-z'\"*][A-Za-z0-9*]*"   # operator
)


def _obj(buf, num):
    m = re.search(rb"(?:^|[\r\n])%d 0 obj" % num, buf)
    return m.end() if m else -1


def read_pdf(path):
    buf = open(path, "rb").read()
    # Page dictionary → contents object + /Properties MCn → OCG object
    page = re.search(rb"/Contents (\d+) 0 R.*?/Properties<<(.*?)>>", buf, re.S)
    contents = int(page.group(1))
    props = {k.decode(): int(v) for k, v in re.findall(rb"/(MC\d+) (\d+) 0 R", page.group(2))}
    names = {}
    for mc, num in props.items():
        i = _obj(buf, num)
        nm = re.search(rb"/Name\((.*?)\)", buf[i:i + 400])
        names[mc] = nm.group(1).decode("latin1")
    i = _obj(buf, contents)
    head = re.search(rb"<<(.*?)>>\s*stream\r?\n", buf[i:i + 400], re.S)
    length = int(re.search(rb"/Length (\d+)", head.group(1)).group(1))
    s = i + head.end()
    return zlib.decompress(buf[s:s + length]), names


def cmyk_hex(c, m, y, k):
    r, g, b = ((1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k))
    return "#%02x%02x%02x" % tuple(round(max(0, min(1, v)) * 255) for v in (r, g, b))


def rgb_hex(r, g, b):
    return "#%02x%02x%02x" % tuple(round(max(0, min(1, v)) * 255) for v in (r, g, b))


def _mul(a, b):
    # PDF matrices [a b c d e f]; returns a×b
    return [a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5]]


def _bez(p0, p1, p2, p3):
    d = math.dist(p0, p1) + math.dist(p1, p2) + math.dist(p2, p3)
    n = max(2, min(24, int(d / 0.6) + 1))
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def parse(path):
    """Return list of features: {layer, kind: fill|stroke, rings: [[(x,y)...]], color, width, evenodd, closed}."""
    data, names = read_pdf(path)
    feats = []
    ctm = [1, 0, 0, 1, 0, 0]
    gs = {"fill": "#000000", "stroke": "#000000", "w": 1.0}
    stack = []
    layer_stack = []
    subpaths, cur = [], None
    closed_flags = []
    operands = []
    in_text = False

    def tp(x, y):
        return (ctm[0] * x + ctm[2] * y + ctm[4], ctm[1] * x + ctm[3] * y + ctm[5])

    def layer():
        for l in reversed(layer_stack):
            if l:
                return l
        return None

    def emit(kind, evenodd=False):
        nonlocal subpaths, cur, closed_flags
        if cur:
            subpaths.append(cur)
            closed_flags.append(False)
        lname = layer()
        rings = [sp for sp in subpaths if len(sp) >= 2]
        if rings and lname and lname not in SKIP_LAYERS and not in_text:
            scale = math.sqrt(abs(ctm[0] * ctm[3] - ctm[1] * ctm[2]))
            if kind in ("fill", "both"):
                feats.append({"layer": lname, "kind": "fill", "rings": rings, "color": gs["fill"], "evenodd": evenodd})
            if kind in ("stroke", "both"):
                feats.append({"layer": lname, "kind": "stroke", "rings": rings, "color": gs["stroke"],
                              "width": gs["w"] * scale, "closed": closed_flags[:len(rings)]})
        subpaths, cur, closed_flags = [], None, []

    for m in TOKEN.finditer(data):
        t = m.group(0)
        c0 = t[:1]
        if c0 in b"-+.0123456789":
            operands.append(float(t))
            continue
        if c0 in b"/(<[]":
            operands.append(t)
            continue
        op = t.decode("latin1")
        n = operands
        if op == "BT":
            in_text = True
        elif op == "ET":
            in_text = False
        elif op == "BDC":
            if len(n) >= 2 and n[-2] == b"/OC":
                layer_stack.append(names.get(n[-1][1:].decode()))
            else:
                layer_stack.append(None)
        elif op == "BMC":
            layer_stack.append(None)
        elif op == "EMC":
            if layer_stack:
                layer_stack.pop()
        elif in_text:
            pass
        elif op == "q":
            stack.append((ctm[:], dict(gs)))
        elif op == "Q":
            if stack:
                ctm, gs = stack.pop()
        elif op == "cm" and len(n) >= 6:
            ctm = _mul([float(v) for v in n[-6:]], ctm)
        elif op == "w" and n:
            gs["w"] = n[-1]
        elif op == "k" and len(n) >= 4:
            gs["fill"] = cmyk_hex(*n[-4:])
        elif op == "K" and len(n) >= 4:
            gs["stroke"] = cmyk_hex(*n[-4:])
        elif op == "rg" and len(n) >= 3:
            gs["fill"] = rgb_hex(*n[-3:])
        elif op == "RG" and len(n) >= 3:
            gs["stroke"] = rgb_hex(*n[-3:])
        elif op == "g" and n:
            gs["fill"] = rgb_hex(n[-1], n[-1], n[-1])
        elif op == "G" and n:
            gs["stroke"] = rgb_hex(n[-1], n[-1], n[-1])
        elif op in ("sc", "scn") and n and all(isinstance(v, float) for v in n):
            v = n
            gs["fill"] = cmyk_hex(*v[-4:]) if len(v) >= 4 else rgb_hex(*v[-3:]) if len(v) == 3 else rgb_hex(v[0], v[0], v[0])
        elif op in ("SC", "SCN") and n and all(isinstance(v, float) for v in n):
            v = n
            gs["stroke"] = cmyk_hex(*v[-4:]) if len(v) >= 4 else rgb_hex(*v[-3:]) if len(v) == 3 else rgb_hex(v[0], v[0], v[0])
        elif op == "m" and len(n) >= 2:
            if cur:
                subpaths.append(cur)
                closed_flags.append(False)
            cur = [tp(n[-2], n[-1])]
            cur_user = (n[-2], n[-1])
        elif op == "l" and len(n) >= 2 and cur is not None:
            cur.append(tp(n[-2], n[-1]))
            cur_user = (n[-2], n[-1])
        elif op in ("c", "v", "y") and cur is not None:
            if op == "c" and len(n) >= 6:
                p1, p2, p3 = (n[-6], n[-5]), (n[-4], n[-3]), (n[-2], n[-1])
            elif op == "v" and len(n) >= 4:
                p1, p2, p3 = cur_user, (n[-4], n[-3]), (n[-2], n[-1])
            elif op == "y" and len(n) >= 4:
                p1, p2, p3 = (n[-4], n[-3]), (n[-2], n[-1]), (n[-2], n[-1])
            else:
                operands = []
                continue
            pts = _bez(cur_user, p1, p2, p3)
            cur.extend(tp(*p) for p in pts)
            cur_user = p3
        elif op == "re" and len(n) >= 4:
            if cur:
                subpaths.append(cur)
                closed_flags.append(False)
            x, y, w, h = n[-4:]
            subpaths.append([tp(x, y), tp(x + w, y), tp(x + w, y + h), tp(x, y + h)])
            closed_flags.append(True)
            cur = None
        elif op == "h":
            if cur:
                subpaths.append(cur)
                closed_flags.append(True)
                cur = None
        elif op in ("f", "F"):
            emit("fill")
        elif op == "f*":
            emit("fill", True)
        elif op == "S":
            emit("stroke")
        elif op == "s":
            if cur:
                subpaths.append(cur)
                closed_flags.append(True)
                cur = None
            emit("stroke")
        elif op in ("B", "B*", "b", "b*"):
            if op.startswith("b") and cur:
                subpaths.append(cur)
                closed_flags.append(True)
                cur = None
            emit("both", op.endswith("*"))
        elif op == "n":
            subpaths, cur, closed_flags = [], None, []
        operands = []
    return feats


def stats(feats):
    from collections import Counter, defaultdict
    by = defaultdict(Counter)
    for f in feats:
        key = (f["kind"], f["color"], round(f.get("width", 0), 2) if f["kind"] == "stroke" else None)
        by[f["layer"]][key] += 1
    for lname, cnt in by.items():
        print(f"== {lname}: {sum(cnt.values())}")
        for k, v in cnt.most_common(14):
            print("   ", v, k)




# ---------------------------------------------------------------------------
# Build step: classify features and encode compact world-space data
# ---------------------------------------------------------------------------
M_PER_PT = 5.0          # 1pt on the artboard = 5m
ART = 3500.0            # artboard size in pt
Q = 10                  # quantisation: 1 unit = 0.1m


def classify(color):
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    h *= 360
    if (h > 300 or h < 15) and s > 0.25 and l < 0.75:
        return "building"
    if 40 <= h <= 75 and l > 0.6 and s < 0.35:
        return "pave"
    if 95 <= h <= 150 and l < 0.75 and s > 0.25:
        return "park"
    if 155 <= h <= 200 and l > 0.6:
        return "water"
    if l > 0.85:
        return "land"
    if l < 0.45 and s < 0.25:
        return "street"
    return "other"


def area(r):
    return 0.5 * sum(r[i - 1][0] * r[i][1] - r[i][0] * r[i - 1][1] for i in range(len(r)))


def pip(pt, ring):
    x, y = pt
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def dp(pts, tol):
    """Douglas-Peucker simplification (iterative)."""
    if len(pts) < 4:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy) or 1e-9
        best, bi = -1, -1
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - ax) - dx * (pts[i][1] - ay)) / L
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            stack += [(a, bi), (bi, b)]
    return [p for p, k in zip(pts, keep) if k]


def clean_ring(r, tol):
    if len(r) > 2 and math.dist(r[0], r[-1]) < 1e-3:
        r = r[:-1]
    out = []
    for p in r:
        if not out or math.dist(out[-1], p) > 1e-3:
            out.append(p)
    if len(out) >= 4:
        # simplify as an open chain anchored at the ring's start
        s = dp(out + [out[0]], tol)[:-1]
        if len(s) >= 3:
            out = s
    return out if len(out) >= 3 else None


def to_polys(rings):
    """Resolve a compound path's rings (nonzero winding) into [outer, *holes] polygons."""
    rs = sorted([r for r in rings if len(r) >= 3], key=lambda r: -abs(area(r)))
    polys = []      # each: [outer, holes..., sign]
    for r in rs:
        a = area(r)
        if abs(a) < 1e-4:
            continue
        host = None
        for p in polys:
            if pip(r[0], p[0]) and all(not pip(r[0], h) for h in p[1:-1]):
                host = p
        if host is None:
            polys.append([r, a > 0])
        elif (a > 0) != host[-1]:
            host.insert(-1, r)          # opposite winding → hole
    return [p[:-1] for p in polys]


def world(p):
    return (round((p[0] - ART / 2) * M_PER_PT * Q), round((ART / 2 - p[1]) * M_PER_PT * Q))


def b64(fmt, arr):
    return base64.b64encode(struct.pack("<%d%s" % (len(arr), fmt), *arr)).decode()


class PolySet:
    def __init__(self):
        self.counts, self.lens, self.xy, self.extra = [], [], [], []

    def add(self, poly, tol, extra=None):
        rings = [clean_ring(r, tol) for r in poly]
        if not rings[0]:
            return False
        rings = [rings[0]] + [h for h in rings[1:] if h]
        self.counts.append(len(rings))
        for r in rings:
            self.lens.append(len(r))
            for p in r:
                self.xy.extend(world(p))
        if extra is not None:
            self.extra.append(extra)
        return True

    def enc(self):
        return {"n": len(self.counts), "counts": b64("H", self.counts), "lens": b64("I", self.lens),
                "xy": b64("i", self.xy)}


class LineSet:
    def __init__(self):
        self.lens, self.xy, self.widths, self.kinds = [], [], [], []

    def add(self, pts, closed, width_m, kind=0, tol=0.08):
        pts = [p for i, p in enumerate(pts) if i == 0 or math.dist(p, pts[i - 1]) > 1e-3]
        if closed and len(pts) > 2:
            pts = pts + [pts[0]]
        pts = dp(pts, tol)
        if len(pts) < 2:
            return
        self.lens.append(len(pts))
        for p in pts:
            self.xy.extend(world(p))
        self.widths.append(max(1, round(width_m * 10)))
        self.kinds.append(kind)

    def enc(self):
        return {"n": len(self.lens), "lens": b64("I", self.lens), "xy": b64("i", self.xy),
                "widths": b64("H", self.widths), "kinds": b64("B", self.kinds)}


def build(src, out):
    feats = parse(src)
    land, elev, water, pave, parks, streets_poly = (PolySet() for _ in range(6))
    bld_polys = []
    streets, paths, canals, beaches = LineSet(), LineSet(), LineSet(), LineSet()
    deep = PolySet()
    for f in feats:
        L, k = f["layer"], f["kind"]
        cls = classify(f["color"])
        if L == "Seas":
            if k == "fill" and f["color"] != "#afe8dd":
                for p in to_polys(f["rings"]):
                    deep.add(p, 0.5)
        elif L == "Island" and k == "fill":
            for p in to_polys(f["rings"]):
                land.add(p, 0.15)
        elif L == "Elevation" and k == "fill":
            for p in to_polys(f["rings"]):
                if cls == "water":
                    water.add(p, 0.15)
                else:
                    # darker green = higher ground
                    lvl = 2 if f["color"] == "#b7f1b4" else 1
                    elev.add(p, 0.3, lvl)
        elif L == "Beaches" and k == "stroke":
            for r, c in zip(f["rings"], f["closed"]):
                beaches.add(r, c, 22)
        elif L == "Canals":
            if k == "fill":
                for p in to_polys(f["rings"]):
                    water.add(p, 0.1)
            else:
                for r, c in zip(f["rings"], f["closed"]):
                    canals.add(r, c, f["width"] * M_PER_PT)
        elif L == "Streets":
            if k == "stroke":
                for r, c in zip(f["rings"], f["closed"]):
                    streets.add(r, c, f["width"] * M_PER_PT)
            elif cls == "street":
                for p in to_polys(f["rings"]):
                    streets_poly.add(p, 0.1)
        elif L == "Paths" and k == "stroke":
            trail = classify(f["color"]) == "park" or f["width"] < 0.5
            for r, c in zip(f["rings"], f["closed"]):
                paths.add(r, c, max(1.5, f["width"] * M_PER_PT), 1 if trail else 0)
        elif L == "Pavement":
            if k == "fill":
                for p in to_polys(f["rings"]):
                    if cls == "building":
                        bld_polys.append(p)
                    else:
                        pave.add(p, 0.1)
            elif cls == "pave":
                for r, c in zip(f["rings"], f["closed"]):
                    streets.add(r, c, f["width"] * M_PER_PT, 1)
        elif L == "Parks" and k == "fill":
            for p in to_polys(f["rings"]):
                parks.add(p, 0.15)
        elif L == "Built" and k == "fill":
            for p in to_polys(f["rings"]):
                if cls == "building":
                    bld_polys.append(p)
                else:
                    # plazas, gardens, ponds and kerbs drawn in the Built layer
                    {"pave": pave, "park": parks, "water": water, "street": streets_poly}.get(cls, pave).add(p, 0.1)

    bld = PolySet()
    ids, floors, seen = [], [], set()
    for p in bld_polys:
        r = p[0]
        cx = sum(q[0] for q in r) / len(r)
        cy = sum(q[1] for q in r) / len(r)
        wx, wz = world((cx, cy))
        h = hashlib.sha1(b"%d,%d" % (round(wx / 10), round(wz / 10))).hexdigest()
        bid = "b" + h[:8]
        while bid in seen:
            h = hashlib.sha1(h.encode()).hexdigest()
            bid = "b" + h[:8]
        if bld.add(p, 0.06):
            seen.add(bid)
            ids.append(bid)
            floors.append(3 + int(h[8:12], 16) % 3)    # 3–5 floors for now

    data = {
        "meta": {"source": src.split("/")[-1], "mPerPt": M_PER_PT, "artboardPt": ART, "quant": 1 / Q,
                 "extentM": ART * M_PER_PT},
        "land": land.enc(), "elevation": dict(elev.enc(), levels=b64("B", elev.extra)),
        "water": water.enc(), "deep": deep.enc(), "pavement": pave.enc(), "parks": parks.enc(),
        "streetAreas": streets_poly.enc(), "streets": streets.enc(), "paths": paths.enc(),
        "canals": canals.enc(), "beaches": beaches.enc(),
        "buildings": dict(bld.enc(), ids=",".join(ids), floors=b64("B", floors)),
    }
    s = json.dumps(data, separators=(",", ":"))
    open(out, "w").write(s)
    print("buildings %d, land %d, parks %d, pavement %d, streets %d, paths %d, canals %d, beaches %d, water %d, elevation %d"
          % (len(ids), len(land.counts), len(parks.counts), len(pave.counts), len(streets.lens), len(paths.lens),
             len(canals.lens), len(beaches.lens), len(water.counts), len(elev.counts)))
    print("wrote %s (%.2f MB)" % (out, len(s) / 1e6))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src = args[0] if args else "data/map/reorganise15.ai"
    if "--stats" in sys.argv:
        stats(parse(src))
    else:
        build(src, args[1] if len(args) > 1 else "data/map/map_data.json")
