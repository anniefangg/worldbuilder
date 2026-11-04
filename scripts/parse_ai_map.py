"""Parse the Illustrator map (.ai, PDF-compatible) into per-layer vector features.

Usage:
    python3 scripts/parse_ai_map.py src.ai [out.json]   # → data/map/map_data.json
    python3 scripts/parse_ai_map.py src.ai --stats      # per-layer colour/width census

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
import os
import re
import struct
import sys
import unicodedata
import zlib
from collections import Counter

SKIP_LAYERS = {"Labels", "Street names"}   # and every layer whose name starts with "Scratch" (skipped())


def skipped(name):
    return name in SKIP_LAYERS or name.lower().startswith("scratch")

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
        if rings and lname and not skipped(lname) and not in_text:
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


def _feature_id(prefix, key, seen):
    h = hashlib.sha1(("%s:%s" % (prefix, key)).encode()).hexdigest()
    fid = prefix + h[:8]
    while fid in seen:
        h = hashlib.sha1(h.encode()).hexdigest()
        fid = prefix + h[:8]
    seen.add(fid)
    return fid


class PolySet:
    """Polygons with holes. With a `prefix`, each polygon also gets a stable feature id
    (hash of its rounded centroid) so the map can attach edits to it."""

    def __init__(self, prefix=None):
        self.counts, self.lens, self.xy, self.extra = [], [], [], []
        self.prefix, self.ids, self.cents, self.sizes, self._seen = prefix, [], [], [], set()

    def add(self, poly, tol, extra=None):
        rings = [clean_ring(r, tol) for r in poly]
        if not rings[0]:
            return False
        rings = [rings[0]] + [h for h in rings[1:] if h]
        if self.prefix:
            w = [world(q) for q in rings[0]]
            cx, cz = sum(q[0] for q in w) / len(w) / Q, sum(q[1] for q in w) / len(w) / Q
            self.ids.append(_feature_id(self.prefix, "%d,%d" % (round(cx / 2), round(cz / 2)), self._seen))
            self.cents.append((cx, cz))
            self.sizes.append(abs(area(rings[0])) * M_PER_PT * M_PER_PT)
        self.counts.append(len(rings))
        for r in rings:
            self.lens.append(len(r))
            for p in r:
                self.xy.extend(world(p))
        if extra is not None:
            self.extra.append(extra)
        return True

    def enc(self):
        d = {"n": len(self.counts), "counts": b64("H", self.counts), "lens": b64("I", self.lens),
             "xy": b64("i", self.xy)}
        if self.prefix:
            d["ids"] = ",".join(self.ids)
        return d


class LineSet:
    def __init__(self, prefix=None):
        self.lens, self.xy, self.widths, self.kinds = [], [], [], []
        self.prefix, self.ids, self.cents, self.sizes, self._seen = prefix, [], [], [], set()

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
        if self.prefix:
            w = [world(q) for q in pts]
            cx, cz = sum(q[0] for q in w) / len(w) / Q, sum(q[1] for q in w) / len(w) / Q
            length = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)) * M_PER_PT
            a, b = world(pts[0]), world(pts[-1])
            key = "%d,%d,%d,%d,%d" % (round(a[0] / 20), round(a[1] / 20), round(b[0] / 20), round(b[1] / 20), round(length / 5))
            self.ids.append(_feature_id(self.prefix, key, self._seen))
            self.cents.append((cx, cz))
            self.sizes.append(length)
        self.widths.append(max(1, round(width_m * 10)))
        self.kinds.append(kind)

    def enc(self):
        d = {"n": len(self.lens), "lens": b64("I", self.lens), "xy": b64("i", self.xy),
             "widths": b64("H", self.widths), "kinds": b64("B", self.kinds)}
        if self.prefix:
            d["ids"] = ",".join(self.ids)
        return d


def _unpack(fmt, b64s):
    raw = base64.b64decode(b64s)
    return struct.unpack("<%d%s" % (len(raw) // struct.calcsize(fmt), fmt), raw)


def decode_buildings(path):
    """{id: (outer ring in metres, floors)} from a previously built map_data.json, or None."""
    try:
        d = json.load(open(path))["buildings"]
    except (OSError, ValueError, KeyError):
        return None
    counts, lens, xy = _unpack("H", d["counts"]), _unpack("I", d["lens"]), _unpack("i", d["xy"])
    ids, floors = d["ids"].split(","), _unpack("B", d["floors"])
    out, ri, vi = {}, 0, 0
    for k, n in enumerate(counts):
        L = lens[ri]
        out[ids[k]] = ([(xy[(vi + j) * 2] / Q, xy[(vi + j) * 2 + 1] / Q) for j in range(L)], floors[k])
        vi += sum(lens[ri:ri + n])
        ri += n
    return out


def _iou(a, b):
    """Approximate intersection-over-union of two rings by grid sampling."""
    xs = [p[0] for p in a + b]
    ys = [p[1] for p in a + b]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    step = max(0.4, max(x1 - x0, y1 - y0) / 40)
    inter = union = 0
    y = y0 + step / 2
    while y < y1:
        x = x0 + step / 2
        while x < x1:
            ia, ib = pip((x, y), a), pip((x, y), b)
            inter += ia and ib
            union += ia or ib
            x += step
        y += step
    return inter / union if union else 0.0


def match_ids(final, previous):
    """Give unmatched new footprints the id of the unmatched old footprint they best overlap.

    final: list of [poly, id, floors, ring_m] (modified in place); previous: decode_buildings().
    """
    new_ids = {f[1] for f in final}
    old_free = {k: v for k, v in previous.items() if k not in new_ids}
    grid = {}
    for k, (ring, _) in old_free.items():
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        grid.setdefault((int(cx // 25), int(cy // 25)), []).append((k, cx, cy))
    kept = sum(1 for f in final if f[1] in previous)
    pairs = []
    for i, f in enumerate(final):
        if f[1] in previous:
            continue
        ring = f[3]
        cx = sum(p[0] for p in ring) / len(ring)
        cy = sum(p[1] for p in ring) / len(ring)
        area_new = abs(area(ring)) or 1e-6
        for gx in range(int(cx // 25) - 1, int(cx // 25) + 2):
            for gy in range(int(cy // 25) - 1, int(cy // 25) + 2):
                for k, ox, oy in grid.get((gx, gy), []):
                    d = math.hypot(cx - ox, cy - oy)
                    if d > 30:
                        continue
                    old_ring = old_free[k][0]
                    score = _iou(ring, old_ring)
                    ratio = abs(area(old_ring)) / area_new
                    if score < 0.5 and d < 3 and 0.7 < ratio < 1.4:
                        score = 0.5
                    if score >= 0.5:
                        pairs.append((score, i, k))
    pairs.sort(reverse=True)
    used_new, used_old = set(), set()
    for score, i, k in pairs:
        if i in used_new or k in used_old:
            continue
        used_new.add(i)
        used_old.add(k)
        final[i][1] = k
        final[i][2] = old_free[k][1]    # keep its old height too
    return {"kept": kept, "remapped": len(used_new), "new": len(final) - kept - len(used_new),
            "removed": len(old_free) - len(used_old)}


def _shape(ring):
    """Translation-, rotation- and mirror-invariant description of a footprint: area, perimeter and the
    cyclic sequence of (edge length, turn angle). Two footprints that are the same shape in different
    places (or turned round) share it."""
    n = len(ring)
    if n < 3:
        return None
    seq = []
    for i in range(n):
        a, b, c = ring[i], ring[(i + 1) % n], ring[(i + 2) % n]
        l1 = math.dist(a, b)
        t = math.atan2(c[1] - b[1], c[0] - b[0]) - math.atan2(b[1] - a[1], b[0] - a[0])
        t = (t + math.pi) % (2 * math.pi) - math.pi
        seq.append((l1, t))
    return {"n": n, "area": abs(area(ring)), "perim": sum(l for l, _ in seq), "seq": seq}


def _same_shape(a, b, tol_len=0.4, tol_ang=0.11):
    if a is None or b is None or a["n"] != b["n"]:
        return False
    if abs(a["area"] - b["area"]) > 0.025 * max(a["area"], 1e-6) or abs(a["perim"] - b["perim"]) > 0.025 * max(a["perim"], 1e-6):
        return False
    n, sa = a["n"], a["seq"]
    sq = b["seq"]
    variants = (
        sq,                                                                    # as drawn
        [(l, -t) for l, t in sq],                                              # mirrored, same vertex order
        [(sq[j][0], -sq[(j - 1) % n][1]) for j in range(n - 1, -1, -1)],       # the same shape traced the other way round
        [(sq[j][0], sq[(j - 1) % n][1]) for j in range(n - 1, -1, -1)],        # mirrored and traced the other way round
    )
    for sb in variants:
        for off in range(n):
            ok = True
            for i in range(n):
                l1, t1 = sa[i]
                l2, t2 = sb[(i + off) % n]
                if abs(l1 - l2) > tol_len or abs(t1 - t2) > tol_ang:
                    ok = False
                    break
            if ok:
                return True
    return False


def find_moves(final, previous, out_dir):
    """After id matching: old footprints that vanished but whose exact shape reappears elsewhere are probably
    buildings that were moved in Illustrator. Writes data/map/reimport_moves.json for the author to confirm
    (a design is never moved silently), listing every candidate when several share the shape."""
    kept_old = {f[1] for f in final if f[1] in previous}
    removed = {k: v for k, v in previous.items() if k not in kept_old}
    fresh = [f for f in final if f[1] not in previous]
    if not removed or not fresh:
        return {"candidates": 0}
    by_n = {}
    for f in fresh:
        sh = _shape(f[3])
        if sh:
            by_n.setdefault(sh["n"], []).append((f, sh))
    moves = []
    for k, (ring, _) in removed.items():
        sh = _shape(ring)
        if not sh:
            continue
        ox = sum(p[0] for p in ring) / len(ring)
        oy = sum(p[1] for p in ring) / len(ring)
        found = []
        for f, fs in by_n.get(sh["n"], []):
            if _same_shape(sh, fs):
                nx = sum(p[0] for p in f[3]) / len(f[3])
                ny = sum(p[1] for p in f[3]) / len(f[3])
                found.append({"id": f[1], "at": [round(nx, 1), round(ny, 1)], "distance": round(math.hypot(nx - ox, ny - oy), 1)})
        if found:
            moves.append({"old": k, "was_at": [round(ox, 1), round(oy, 1)], "area": round(sh["area"], 1), "candidates": found})
    claims = {}
    for m in moves:
        for c in m["candidates"]:
            claims[c["id"]] = claims.get(c["id"], 0) + 1
    for m in moves:
        m["unambiguous"] = len(m["candidates"]) == 1 and claims[m["candidates"][0]["id"]] == 1
    path = os.path.join(out_dir, "reimport_moves.json")
    json.dump({"note": "Old building ids that no longer exist, with new footprints of the same shape. Check which old ids have edits, then confirm each pair with the author before moving a design.",
               "moves": moves}, open(path, "w"), indent=1)
    return {"candidates": len(moves), "unambiguous": sum(1 for m in moves if m["unambiguous"]), "file": path}


def decode_features(path, key):
    """{id: (centroid, size)} for one feature layer of a previous build, or None."""
    try:
        d = json.load(open(path))[key]
    except (OSError, ValueError, KeyError):
        return None
    if "ids" not in d:
        return None
    ids, xy, out, vi = d["ids"].split(","), _unpack("i", d["xy"]), {}, 0
    if "counts" in d:          # polygons: centroid and area of the outer ring
        counts, lens, ri = _unpack("H", d["counts"]), _unpack("I", d["lens"]), 0
        for k, n in enumerate(counts):
            L = lens[ri]
            ring = [(xy[(vi + j) * 2] / Q, xy[(vi + j) * 2 + 1] / Q) for j in range(L)]
            out[ids[k]] = ((sum(p[0] for p in ring) / L, sum(p[1] for p in ring) / L), abs(area(ring)))
            vi += sum(lens[ri:ri + n])
            ri += n
    else:                      # lines: centroid of points and length
        for k, L in enumerate(_unpack("I", d["lens"])):
            pts = [(xy[(vi + j) * 2] / Q, xy[(vi + j) * 2 + 1] / Q) for j in range(L)]
            out[ids[k]] = ((sum(p[0] for p in pts) / L, sum(p[1] for p in pts) / L),
                           sum(math.dist(pts[i], pts[i + 1]) for i in range(L - 1)))
            vi += L
    return out


def match_feature_ids(fset, previous):
    """Give moved or redrawn parks, streets, canals… the id of the nearby old feature of similar size."""
    if not previous:
        return None
    cur = set(fset.ids)
    free = {k: v for k, v in previous.items() if k not in cur}
    kept = sum(1 for i in fset.ids if i in previous)
    pairs = []
    for i, fid in enumerate(fset.ids):
        if fid in previous:
            continue
        (cx, cz), size = fset.cents[i], fset.sizes[i] or 1e-6
        for k, ((ox, oz), osize) in free.items():
            d = math.hypot(cx - ox, cz - oz)
            if d < 12 and 0.6 < osize / size < 1.6:
                pairs.append((d, i, k))
    pairs.sort()
    used_i, used_k = set(), set()
    for d, i, k in pairs:
        if i in used_i or k in used_k:
            continue
        used_i.add(i)
        used_k.add(k)
        fset.ids[i] = k
    return kept, len(used_i), len(fset.ids) - kept - len(used_i), len(free) - len(used_k)


# ---- street names: the "Street names" layer is live type on a path, so each label's text and the place of every letter
# can be read back. The labels only say WHICH street has WHICH name: the viewer places its own text (see the labeller in map_template.html).
GLYPHS = {"space": " ", "hyphen": "-", "period": ".", "comma": ",", "quotesingle": "'", "quoteright": "’", "parenleft": "(", "parenright": ")",
          "slash": "/", "ampersand": "&", "colon": ":", "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
          "seven": "7", "eight": "8", "nine": "9", "f_i": "fi", "f_l": "fl", "f_f": "ff", "f_f_i": "ffi", "f_f_l": "ffl", "f_t": "ft", "f_b": "fb",
          "f_h": "fh", "f_j": "fj", "f_k": "fk", "t_t": "tt", "T_h": "Th", "s_t": "st", "ordfeminine": "ª", "ordmasculine": "º"}
for _base, _marks in (("a", "acute dieresis grave circumflex tilde"), ("e", "acute dieresis grave circumflex"), ("i", "acute dieresis grave circumflex"),
                      ("o", "acute dieresis grave circumflex tilde"), ("u", "acute dieresis grave circumflex"), ("n", "tilde"), ("c", "cedilla")):
    for _m in _marks.split():
        _c = {"acute": "́", "dieresis": "̈", "grave": "̀", "circumflex": "̂", "tilde": "̃", "cedilla": "̧"}[_m]
        for _b in (_base, _base.upper()):
            GLYPHS[_b + _m] = unicodedata.normalize("NFC", _b + _c)
LABEL_JUMP = 1.0   # points (5 m) past a letter's own advance: the next letter belongs to another label


def _font_tables(buf):
    """{font name: (code → text, first char, widths)} from the page's font dictionary and its encodings."""
    def body(n):
        i = _obj(buf, n)
        return buf[i:buf.find(b"endobj", i)] if i >= 0 else b""
    m = re.search(rb"/Font<<(.*?)>>", buf, re.S)
    out = {}
    for name, num in re.findall(rb"/(T1_\d+|C\d_\d+|TT\d+) (\d+) 0 R", m.group(1)) if m else []:
        o = body(int(num))
        table = {i: bytes([i]).decode("cp1252", "replace") for i in range(256)}
        enc = re.search(rb"/Encoding (\d+) 0 R", o)
        if enc:
            arr = re.search(rb"/Differences\s*\[(.*?)\]", body(int(enc.group(1))), re.S)
            code = 0
            for tok in re.findall(rb"/[^\s/\]]+|\d+", arr.group(1)) if arr else []:
                if tok[:1] == b"/":
                    g = tok[1:].decode("latin1")
                    table[code] = g if len(g) == 1 else GLYPHS.get(g, "�")
                    code += 1
                else:
                    code = int(tok)
        fc = re.search(rb"/FirstChar (\d+)", o)
        w = re.search(rb"/Widths\s*\[(.*?)\]", o, re.S)
        out[name] = (table, int(fc.group(1)) if fc else 0, [float(x) for x in w.group(1).split()] if w else [])
    return out


def _pdf_string(tok):
    """A PDF string token → its character codes."""
    if tok[:1] == b"<":
        h = re.sub(rb"\s", b"", tok[1:-1])
        return list(bytes.fromhex((h + b"0" * (len(h) % 2)).decode()))
    s, out, i = tok[1:-1], [], 0
    while i < len(s):
        c = s[i]
        if c == 92 and i + 1 < len(s):
            i += 1
            c = s[i]
            if 48 <= c <= 55:
                j, v = i, 0
                while j < len(s) and j < i + 3 and 48 <= s[j] <= 55:
                    v = v * 8 + s[j] - 48
                    j += 1
                out.append(v & 255)
                i = j
                continue
            c = {110: 10, 114: 13, 116: 9, 98: 8, 102: 12}.get(c, c)
        out.append(c)
        i += 1
    return out


def street_labels(path, layer_name="Street names"):
    """Every label on the layer: [(text, [(x, z) world metres of each letter])]. One text block can hold many labels, so a
    jump between letters starts a new one."""
    data, names = read_pdf(path)
    fonts = _font_tables(open(path, "rb").read())
    I = [1, 0, 0, 1, 0, 0]
    ctm, cs, tm, lm = I[:], [], I[:], I[:]
    font, size, tc, tw, tl = None, 1.0, 0.0, 0.0, 0.0
    layers, operands, block, labels = [], [], None, []

    def show(codes):
        nonlocal tm
        table, fc, widths = fonts.get(font, ({}, 0, []))
        for c in codes:
            x, y = tm[4], tm[5]
            adv = (widths[c - fc] if 0 <= c - fc < len(widths) else 500) / 1000 * size
            block.append((table.get(c, "�"), ctm[0] * x + ctm[2] * y + ctm[4], ctm[1] * x + ctm[3] * y + ctm[5], adv * math.hypot(tm[0], tm[1])))
            step = adv + tc + (tw if c == 32 else 0)
            tm = [tm[0], tm[1], tm[2], tm[3], tm[4] + step * tm[0], tm[5] + step * tm[1]]

    def finish():
        run = []

        def flush():
            text = re.sub(r"\s+", " ", "".join(g[0] for g in run)).strip()
            if text:
                pts = [(a / Q, b / Q) for a, b in (world((g[1], g[2])) for g in run)]
                labels.append((text, pts))
        for g in block:
            if run and math.dist((g[1], g[2]), (run[-1][1], run[-1][2])) - run[-1][3] > LABEL_JUMP:
                flush()
                run = []
            run.append(g)
        flush()

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
        if op == "BDC":
            layers.append(names.get(n[-1][1:].decode()) if len(n) >= 2 and n[-2] == b"/OC" else None)
        elif op == "BMC":
            layers.append(None)
        elif op == "EMC":
            if layers:
                layers.pop()
        elif op == "q":
            cs.append(ctm[:])
        elif op == "Q":
            if cs:
                ctm = cs.pop()
        elif op == "cm" and len(n) >= 6:
            ctm = _mul([float(v) for v in n[-6:]], ctm)
        elif op == "BT":
            tm, lm, block = I[:], I[:], []
        elif op == "ET":
            if block and next((x for x in reversed(layers) if x), None) == layer_name:
                finish()
            block = None
        elif op == "Tf" and len(n) >= 2 and isinstance(n[-2], bytes):
            font, size = n[-2][1:], n[-1]
        elif op == "Tc" and n:
            tc = n[-1]
        elif op == "Tw" and n:
            tw = n[-1]
        elif op == "TL" and n:
            tl = n[-1]
        elif op == "Tm" and len(n) >= 6:
            tm = [float(v) for v in n[-6:]]
            lm = tm[:]
        elif op in ("Td", "TD") and len(n) >= 2:
            if op == "TD":
                tl = -n[-1]
            lm = [lm[0], lm[1], lm[2], lm[3], lm[4] + n[-2] * lm[0] + n[-1] * lm[2], lm[5] + n[-2] * lm[1] + n[-1] * lm[3]]
            tm = lm[:]
        elif op == "T*":
            lm = [lm[0], lm[1], lm[2], lm[3], lm[4] - tl * lm[2], lm[5] - tl * lm[3]]
            tm = lm[:]
        elif op == "Tj" and block is not None and n and isinstance(n[-1], bytes):
            show(_pdf_string(n[-1]))
        elif op == "TJ" and block is not None:
            for v in n:
                if isinstance(v, bytes) and v[:1] in (b"(", b"<"):
                    show(_pdf_string(v))
                elif isinstance(v, float):
                    d = -v / 1000 * size
                    tm = [tm[0], tm[1], tm[2], tm[3], tm[4] + d * tm[0], tm[5] + d * tm[1]]
        operands = []
    return labels


class _LineIndex:
    """The street and path centrelines, with a grid of their segments, for matching labels to them."""
    CELL = 40.0

    def __init__(self, sets):
        self.lines, self.grid = [], {}
        for fset in sets:
            v = 0
            for k, n in enumerate(fset.lens):
                pts = [(fset.xy[(v + j) * 2] / Q, fset.xy[(v + j) * 2 + 1] / Q) for j in range(n)]
                v += n
                cum = [0.0]
                for i in range(n - 1):
                    cum.append(cum[-1] + math.dist(pts[i], pts[i + 1]))
                idx = len(self.lines)
                self.lines.append({"id": fset.ids[k], "pts": pts, "cum": cum, "w": fset.widths[k] / 10, "sub": fset.kinds[k], "len": cum[-1]})
                for i in range(n - 1):
                    a, b = pts[i], pts[i + 1]
                    steps = max(1, int(math.dist(a, b) / self.CELL))
                    for q in range(steps + 1):
                        key = (int((a[0] + (b[0] - a[0]) * q / steps) // self.CELL), int((a[1] + (b[1] - a[1]) * q / steps) // self.CELL))
                        self.grid.setdefault(key, set()).add(idx)

    def near(self, pts, reach):
        out, r = set(), int(reach // self.CELL) + 1
        for p in pts:
            cx, cz = int(p[0] // self.CELL), int(p[1] // self.CELL)
            for i in range(-r, r + 1):
                for j in range(-r, r + 1):
                    out |= self.grid.get((cx + i, cz + j), set())
        return out

    def nearest(self, line, p):
        """(distance, arc length, segment direction) of the point of a line nearest p."""
        pts, cum, best = line["pts"], line["cum"], (1e18, 0.0, 0.0)
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            dx, dz = b[0] - a[0], b[1] - a[1]
            l2 = dx * dx + dz * dz or 1e-9
            t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dz) / l2))
            d = math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dz)
            if d < best[0]:
                best = (d, cum[i] + t * math.sqrt(l2), math.atan2(dz, dx))
        return best


def _fit_label(ix, line, pts):
    """How well a label lies along a line: (mean distance, mean angle off, arc length start, arc length end)."""
    k = max(1, len(pts) // 6)
    samples = pts[::k] + [pts[-1]]
    ds, angs, arcs = [], [], []
    for i, p in enumerate(samples):
        d, s, a = ix.nearest(line, p)
        ds.append(d)
        arcs.append(s)
        q0, q1 = samples[max(0, i - 1)], samples[min(len(samples) - 1, i + 1)]
        if q0 != q1:
            la = math.atan2(q1[1] - q0[1], q1[0] - q0[0])
            angs.append(abs(((la - a + math.pi / 2) % math.pi) - math.pi / 2))
    return sum(ds) / len(ds), sum(angs) / len(angs) if angs else 0.0, min(arcs), max(arcs)


def bind_street_names(labels, streets, paths):
    """Which stretch of which line has which name. Returns ({names, lines: {id: [name, s1, name, s2, name…]}}, report): a line's
    entry alternates a name's index with the arc length where the next name takes over."""
    ix = _LineIndex([streets, paths])
    bound, stray = {}, []
    for text, pts in labels:
        mid = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
        best = None
        for li in ix.near([pts[0], mid, pts[-1]], 30):
            line = ix.lines[li]
            d, a, s0, s1 = _fit_label(ix, line, pts)
            score = d + a * 25
            if best is None or score < best[0]:
                best = (score, d, a, s0, s1, li)
        if best and best[2] < 0.5 and best[1] <= max(9.0, ix.lines[best[5]]["w"] / 2 + 5):
            bound.setdefault(best[5], []).append(((best[3] + best[4]) / 2, best[3], best[4], text))
        else:
            stray.append({"text": text, "x": round(mid[0]), "z": round(mid[1]), "pts": pts, "off": round(best[1], 1) if best else None})
    # a label a little further out still names a parallel line nothing else names (the line moved after it was typed)
    left = []
    for st in stray:
        best = None
        for li in ix.near([st["pts"][0], st["pts"][-1]], 40):
            if li in bound:
                continue
            d, a, s0, s1 = _fit_label(ix, ix.lines[li], st["pts"])
            if a < 0.25 and d < 40 and (best is None or d < best[0]):
                best = (d, s0, s1, li)
        if best:
            bound.setdefault(best[3], []).append(((best[1] + best[2]) / 2, best[1], best[2], st["text"]))
        else:
            left.append({k: st[k] for k in ("text", "x", "z", "off")})
    # places where a name can change: where another line meets this one, or where it turns a corner
    ends = {}
    for li, line in enumerate(ix.lines):
        for e in (line["pts"][0], line["pts"][-1]):
            ends.setdefault((int(e[0] // ix.CELL), int(e[1] // ix.CELL)), []).append((li, e))

    def breaks(li):
        line, out = ix.lines[li], []
        pts, cum = line["pts"], line["cum"]
        cells = set()
        for i in range(len(pts) - 1):
            a, b = pts[i], pts[i + 1]
            steps = max(1, int(math.dist(a, b) / ix.CELL))
            for q in range(steps + 1):
                cells.add((int((a[0] + (b[0] - a[0]) * q / steps) // ix.CELL), int((a[1] + (b[1] - a[1]) * q / steps) // ix.CELL)))
        for c in cells:
            for i in range(-1, 2):
                for j in range(-1, 2):
                    for other, e in ends.get((c[0] + i, c[1] + j), ()):
                        if other != li:
                            d, s, _ = ix.nearest(line, e)
                            if d <= line["w"] / 2 + ix.lines[other]["w"] / 2 + 2:
                                out.append(s)
        for i in range(1, len(pts) - 1):
            a0 = math.atan2(pts[i][1] - pts[i - 1][1], pts[i][0] - pts[i - 1][0])
            a1 = math.atan2(pts[i + 1][1] - pts[i][1], pts[i + 1][0] - pts[i][0])
            if abs(((a1 - a0 + math.pi) % (2 * math.pi)) - math.pi) > 0.5:
                out.append(cum[i])
        return sorted(out)
    names, index, lines, odd = [], {}, {}, []

    def nid(t):
        if t not in index:
            index[t] = len(names)
            names.append(t)
        return index[t]
    for li in sorted(bound):
        line, ls = ix.lines[li], sorted(bound[li])
        # A name sandwiched between two of another, lying on a line it does not turn off from, is a side street's label caught by mistake
        groups = []
        for s, s0, s1, t in ls:
            if groups and groups[-1][0] == t:
                groups[-1][2] = s1
            else:
                groups.append([t, s0, s1])
        if len(groups) >= 3:
            kept = []
            for i, g in enumerate(groups):
                if 0 < i < len(groups) - 1 and groups[i - 1][0] == groups[i + 1][0]:
                    odd.append({"id": line["id"], "name": g[0], "on": groups[i - 1][0]})
                    continue
                kept.append(g)
            merged = []
            for g in kept:
                if merged and merged[-1][0] == g[0]:
                    merged[-1][2] = g[2]
                else:
                    merged.append(g)
            groups = merged
        entry = [nid(groups[0][0])]
        if len(groups) > 1:
            bs = breaks(li)
            for g0, g1 in zip(groups, groups[1:]):
                a, b = g0[2], max(g0[2], g1[1])
                mid = (a + b) / 2
                inside = [x for x in bs if a - 1 <= x <= b + 1]
                cut = min(inside, key=lambda x: abs(x - mid)) if inside else mid
                entry += [round(cut, 1), nid(g1[0])]
        lines[line["id"]] = entry
    named = set(lines)
    unnamed = [x for x in ix.lines if x["id"] not in named and x["id"].startswith("st")]
    report = {"labels": len(labels), "stray": left, "odd": odd, "several": sum(1 for v in lines.values() if len(v) > 1),
              "unnamed_lines": sorted(({"id": x["id"], "len": round(x["len"]), "x": round(sum(p[0] for p in x["pts"]) / len(x["pts"])), "z": round(sum(p[1] for p in x["pts"]) / len(x["pts"]))} for x in unnamed), key=lambda r: -r["len"]),
              "street_km": round(sum(x["len"] for x in ix.lines if x["id"].startswith("st")) / 1000), "named_km": round(sum(x["len"] for x in ix.lines if x["id"].startswith("st") and x["id"] in named) / 1000)}
    report["counts"] = Counter(t for t, _ in labels)
    return {"names": names, "lines": lines}, report


def street_names_report(rep, out_dir):
    """data/map/street_names_report.md, for the author: typing to check, labels on no street, streets with no label."""
    import difflib
    c = rep["counts"]
    plain = lambda s: "".join(ch for ch in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(ch) != "Mn")
    TYPES = ("Calle", "Camino", "Callejón", "Avenida", "Paseo", "Andador", "Puente", "Plaza", "Calzada", "Bulevar", "Pasaje", "Esquina", "Isla", "Gran", "Media")
    spacing = sorted(t for t in c if re.search(r"[a-zà-ÿ][A-ZÀ-Þ]", t))
    notype = sorted(t for t in c if t.split(" ")[0] not in TYPES and t not in spacing)
    seen, accents, letters, swaps, similar = set(), [], [], [], []
    words = sorted(c, key=lambda t: (-c[t], t))
    for t in words:
        for u in difflib.get_close_matches(t, [w for w in words if w != t], n=4, cutoff=0.86):
            key = tuple(sorted((t, u)))
            if key in seen or (t.split("(")[0].strip() == u.split("(")[0].strip()):
                continue
            seen.add(key)
            a, b = key
            pair = "%s (%d) / %s (%d)" % (a, c[a], b, c[b])
            pa, pb = plain(a), plain(b)
            if pa == pb:
                accents.append(pair)
            elif pa.replace(" de ", " ").replace(" del ", " ") == pb.replace(" de ", " ").replace(" del ", " "):
                letters.append(pair)
            elif len(a) == len(b) and sum(x != y for x, y in zip(pa, pb)) == 2 and sorted(pa) == sorted(pb):
                swaps.append(pair)
            elif abs(len(a) - len(b)) == 1 and min(c[a], c[b]) <= 1 and max(c[a], c[b]) >= 2 and difflib.SequenceMatcher(None, pa, pb).ratio() > 0.9:
                letters.append(pair)
            else:
                similar.append(pair)
    L = ["# Street names: things to check in the Illustrator file", "",
         "Written by `scripts/parse_ai_map.py` at each import. The map shows names exactly as typed, so a fix in Illustrator is picked up by the next re-import.", "",
         "%d labels, %d different names. %d of %d km of street carry a name." % (rep["labels"], len(c), rep["named_km"], rep["street_km"]), ""]

    def section(title, intro, rows):
        L.extend(["## %s (%d)" % (title, len(rows)), "", intro, ""])
        L.extend("- " + r for r in rows)
        L.append("")
    section("Missing spaces", "Two words run together.", spacing)
    section("Names without a street type", "These don't begin with Calle, Camino, Avenida and so on.", notype)
    section("Same name, different accents", "The number is how many labels use that spelling.", accents)
    section("Letters swapped", "Probably one street spelt two ways.", swaps)
    section("A letter or a \"de\" different", "Possibly one street spelt two ways: the rarer spelling is often the slip.", letters)
    section("Similar names", "Most of these will be different streets, listed only in case.", similar)
    section("Labels on no street", "These sit too far from any street or path line to say which one they name, so they are not used.",
            ["%s at (%d, %d)%s" % (s["text"], s["x"], s["z"], ", %s m from the nearest line" % s["off"] if s["off"] is not None else ", nothing nearby") for s in rep["stray"]])
    section("Labels ignored as a side street's", "A name in the middle of a line that has another name on both sides of it. It is treated as a stray label and left off that line.",
            ["%s, on %s (`%s`)" % (o["name"], o["on"], o["id"]) for o in rep["odd"]])
    section("Longest streets with no label", "Streets with no name, longest first. Only the 40 longest are listed.",
            ["`%s`, %d m, around (%d, %d)" % (u["id"], u["len"], u["x"], u["z"]) for u in rep["unnamed_lines"][:40]])
    path = os.path.join(out_dir, "street_names_report.md")
    open(path, "w").write("\n".join(L))
    return {"file": path, "spacing": len(spacing), "notype": len(notype), "accents": len(accents), "swaps": len(swaps), "letters": len(letters), "similar": len(similar)}


def elevation_levels(bands):
    """Topographic bands, each drawn inside the one below it: level 1 is 50-100 m, 2 is 100-150 m, … (the
    plain island outside every band is 0-50 m). A band's level is its colour's level, and a colour's level
    is how deeply that colour's shapes are usually nested. So a caldera (a lower band drawn inside a higher
    one) keeps its own, lower level instead of counting as one more step up."""
    polys = [(p, c, abs(area(p[0]))) for p, c in bands if abs(area(p[0])) > 1e-3]
    depth = {}
    for i, (p, c, a) in enumerate(polys):
        depth[i] = 1 + sum(1 for j, (q, _, b) in enumerate(polys) if j != i and b > a and pip(p[0][0], q[0]))
    votes = {}
    for i, (p, c, a) in enumerate(polys):
        votes.setdefault(c, {}).setdefault(depth[i], 0)
        votes[c][depth[i]] += a
    level = {c: max(v, key=v.get) for c, v in votes.items()}
    return [(p, level[c]) for p, c, a in polys]


def build(src, out):
    feats = parse(src)
    land, elev, streets_poly = PolySet(), PolySet(), PolySet()
    water, pave, parks = PolySet("wt"), PolySet("pz"), PolySet("pk")
    bld_polys = []
    streets, paths, canals, beaches = LineSet("st"), LineSet("pt"), LineSet("cn"), LineSet("bc")
    deep = PolySet()
    bands = []          # Elevation fills: (poly, colour), levelled by elevation_levels() once all are read
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
                    bands.append((p, f["color"]))
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

    for p, lvl in elevation_levels(bands):
        elev.add(p, 0.3, lvl)
    if bands:
        print("elevation: %d bands, levels %s (each 50 m; the plain island is 0-50 m)" % (len(elev.counts), sorted(set(elev.extra))))

    # Stable ids: a hash of each footprint's position. On re-import, footprints that were
    # moved or redrawn inherit the id of the old footprint they overlap, so edits made in
    # the 3D map (stored by id) stay attached. See match_ids().
    cand = []
    for p in bld_polys:
        r = p[0]
        if not clean_ring(r, 0.06):
            continue    # degenerate sliver, dropped from the output anyway
        cx = sum(q[0] for q in r) / len(r)
        cy = sum(q[1] for q in r) / len(r)
        wx, wz = world((cx, cy))
        h = hashlib.sha1(b"%d,%d" % (round(wx / 10), round(wz / 10))).hexdigest()
        cand.append((p, h, [(world(q)[0] / Q, world(q)[1] / Q) for q in r]))
    previous = decode_buildings(out)
    seen, final = set(), []
    for p, h, ring in cand:
        bid = "b" + h[:8]
        while bid in seen:
            h = hashlib.sha1(h.encode()).hexdigest()
            bid = "b" + h[:8]
        seen.add(bid)
        final.append([p, bid, 3 + int(h[8:12], 16) % 3, ring])    # 3–5 floors for now
    if previous:
        report = match_ids(final, previous)
        print("re-import buildings: %(kept)d kept, %(remapped)d remapped, %(new)d new, %(removed)d removed" % report)
        mv = find_moves(final, previous, os.path.dirname(out) or ".")
        if mv["candidates"]:
            print("re-import: %(candidates)d removed footprints have a look-alike among the new ones (%(unambiguous)d unambiguous): %(file)s" % mv)
        else:
            print("re-import: no removed footprint reappears elsewhere, so no moved buildings to confirm")
        for key, fset in (("parks", parks), ("pavement", pave), ("water", water), ("streets", streets),
                          ("paths", paths), ("canals", canals), ("beaches", beaches)):
            rep = match_feature_ids(fset, decode_features(out, key))
            if rep:
                print("re-import %s: %d kept, %d remapped, %d new, %d removed" % ((key,) + rep))
    bld = PolySet()
    ids, floors = [], []
    for p, bid, fl, _ in final:
        if bld.add(p, 0.06):
            ids.append(bid)
            floors.append(fl)

    street_names, name_report = bind_street_names(street_labels(src), streets, paths)
    nr = street_names_report(name_report, os.path.dirname(os.path.abspath(out)))
    print("street names: %d labels, %d names, on %d of %d km of street; %d lines change name, %d labels on no street, %d side-street labels ignored; report %s"
          % (name_report["labels"], len(street_names["names"]), name_report["named_km"], name_report["street_km"], name_report["several"],
             len(name_report["stray"]), len(name_report["odd"]), nr["file"]))
    data = {
        "meta": {"source": src.split("/")[-1], "mPerPt": M_PER_PT, "artboardPt": ART, "quant": 1 / Q,
                 "extentM": ART * M_PER_PT},
        "land": land.enc(), "elevation": dict(elev.enc(), levels=b64("B", elev.extra)),
        "water": water.enc(), "deep": deep.enc(), "pavement": pave.enc(), "parks": parks.enc(),
        "streetAreas": streets_poly.enc(), "streets": streets.enc(), "paths": paths.enc(),
        "canals": canals.enc(), "beaches": beaches.enc(),
        "buildings": dict(bld.enc(), ids=",".join(ids), floors=b64("B", floors)),
        "streetNames": street_names,
    }
    s = json.dumps(data, separators=(",", ":"))
    open(out, "w").write(s)
    print("buildings %d, land %d, parks %d, pavement %d, streets %d, paths %d, canals %d, beaches %d, water %d, elevation %d"
          % (len(ids), len(land.counts), len(parks.counts), len(pave.counts), len(streets.lens), len(paths.lens),
             len(canals.lens), len(beaches.lens), len(water.counts), len(elev.counts)))
    print("wrote %s (%.2f MB)" % (out, len(s) / 1e6))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    unknown = [a for a in sys.argv[1:] if a.startswith("--") and a != "--stats"]
    if unknown or not args:
        sys.exit("usage: parse_ai_map.py SRC.ai [OUT.json] | SRC.ai --stats" + (" (unknown: %s)" % " ".join(unknown) if unknown else ""))
    src = args[0]
    if "--stats" in sys.argv:
        stats(parse(src))
    else:
        build(src, args[1] if len(args) > 1 else "data/map/map_data.json")
