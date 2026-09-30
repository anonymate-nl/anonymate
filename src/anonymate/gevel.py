"""Blootgestelde gevel per windrichting, uit de pandcontouren van de BAG.

Voor A_sol per gevelrichting (kladbloknotitie 2, stap A): per pand de lengte van de buitenmuur
per windrichting (acht sectoren van 45 graden, kompas, met de klok mee vanaf noord), zonder de
muren die het pand met een buurpand deelt (scheidingsmuren). Alleen numpy en de standaardbibliotheek;
geen shapely of GDAL.

Per contourrand (RD-coordinaten, meter):

* de buitennormaal volgt uit de ringrichting (buitenring tegen de klok in, gaten met de klok mee:
  het pand ligt links van elke rand), de sector uit het kompasazimut van die normaal;
* een rand is (deels) gedeeld als een rand van een ander pand er binnen :data:`TOLERANTIE__m`
  (0,5 m) van ligt en er bijna evenwijdig aan loopt (hoek < 15 graden); de gedeelde lengte is de
  lengte van de overlap van alle zulke buurranden, de blootgestelde lengte de rest;
* de hoofdas van het pand is de richting van de langste rand; een zijgevel is een blootgestelde
  rand waarvan de normaal loodrecht op de hoofdas staat (hoek met de loodlijn hoogstens 45
  graden). Bij een rijwoning is dat de lange zijmuur van een hoekwoning (de diepte), niet de
  voor- of achtergevel.

De RD-rasterrichting wijkt in Nederland hooguit ongeveer twee graden af van het ware noorden
(meridiaanconvergentie); daar wordt niet voor gecorrigeerd.
"""
from __future__ import annotations

import struct

import numpy as np

SECTOREN = 8
TOLERANTIE__m = 0.5
SIN_HOEK_MAX__0 = 0.26           # sin(15 graden): "bijna evenwijdig"
ZIJ_COS_MAX__0 = 0.7071          # normaal hoogstens 45 graden van de loodlijn op de hoofdas
_CEL__m = 8.0


# ------------------------------------------------------------------------------------------------
# GeoPackage geometry
# ------------------------------------------------------------------------------------------------

def gpkg_rings(blob: bytes | None) -> list[tuple[np.ndarray, bool]]:
    """The rings of a GeoPackage (multi)polygon blob as ``[(xy (n, 2), is_hole), ...]``; empty
    for a missing, empty or non-polygon geometry."""
    if not blob or blob[:2] != b"GP" or blob[3] & 0b10000:
        return []
    env = (blob[3] >> 1) & 0b111
    off = 8 + (0, 32, 48, 48, 64)[env] if env <= 4 else 8
    out: list[tuple[np.ndarray, bool]] = []
    try:
        _wkb_polygons(blob, off, out)
    except (struct.error, ValueError):
        return []
    return out


def _wkb_polygons(b: bytes, off: int, out: list) -> int:
    e = "<" if b[off] == 1 else ">"
    t = struct.unpack_from(e + "I", b, off + 1)[0]
    off += 5
    code = t & 0x0FFFFFFF
    base, iso = code % 1000, code // 1000
    dim = 2 + bool(t & 0x80000000 or iso in (1, 3)) + bool(t & 0x40000000 or iso in (2, 3))
    if base == 3:
        nr = struct.unpack_from(e + "I", b, off)[0]
        off += 4
        for k in range(nr):
            npt = struct.unpack_from(e + "I", b, off)[0]
            off += 4
            pts = np.frombuffer(b, dtype=e + "f8", count=npt * dim, offset=off)
            off += npt * dim * 8
            out.append((pts.reshape(npt, dim)[:, :2].astype(float), k > 0))
    elif base == 6:
        n = struct.unpack_from(e + "I", b, off)[0]
        off += 4
        for _ in range(n):
            off = _wkb_polygons(b, off, out)
    else:
        raise ValueError(f"geen polygoon: type {t}")
    return off


def edges_from_rings(rings_per_pand: list[list[tuple[np.ndarray, bool]]]):
    """All contour edges of a list of panden: ``(pand, x1, y1, x2, y2)`` as flat arrays, every ring
    oriented so the building lies to the left of the direction of travel."""
    pid, xs, ys, xe, ye = [], [], [], [], []
    for i, rings in enumerate(rings_per_pand):
        for xy, hole in rings:
            if len(xy) < 4:
                continue
            x, y = xy[:, 0], xy[:, 1]
            area2 = np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])   # shoelace (closed ring)
            if (area2 > 0) == hole:          # outer ring must run counter-clockwise, holes not
                xy = xy[::-1]
            pid.append(np.full(len(xy) - 1, i, dtype=np.int64))
            xs.append(xy[:-1, 0]), ys.append(xy[:-1, 1])
            xe.append(xy[1:, 0]), ye.append(xy[1:, 1])
    if not pid:
        z = np.zeros(0)
        return np.zeros(0, dtype=np.int64), z, z, z, z
    return tuple(np.concatenate(a) for a in (pid, xs, ys, xe, ye))


# ------------------------------------------------------------------------------------------------
# exposed façade per sector
# ------------------------------------------------------------------------------------------------

def _cells(x1, y1, x2, y2, tol, cell=_CEL__m):
    """Grid-cell keys (and the edge index) covering each edge's bounding box, grown by ``tol``."""
    i0 = np.floor((np.minimum(x1, x2) - tol) / cell).astype(np.int64)
    i1 = np.floor((np.maximum(x1, x2) + tol) / cell).astype(np.int64)
    j0 = np.floor((np.minimum(y1, y2) - tol) / cell).astype(np.int64)
    j1 = np.floor((np.maximum(y1, y2) + tol) / cell).astype(np.int64)
    nx, ny = i1 - i0 + 1, j1 - j0 + 1
    cnt = nx * ny
    eid = np.repeat(np.arange(len(x1)), cnt)
    k = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
    ci = i0[eid] + k % nx[eid]
    cj = j0[eid] + k // nx[eid]
    return ci * 4_000_000 + cj, eid


def shared_length(pid, x1, y1, x2, y2, query, *, tol: float = TOLERANTIE__m,
                  max_pairs: int = 4_000_000) -> np.ndarray:
    """Per edge (array over all edges, only ``query`` filled): the length [m] along which an edge
    of *another* pand lies within ``tol`` of it and nearly parallel to it, summed over those
    neighbour edges."""
    n = len(x1)
    L = np.hypot(x2 - x1, y2 - y1)
    with np.errstate(divide="ignore", invalid="ignore"):
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
    out = np.zeros(n)
    if len(query) == 0:
        return out
    bkey, beid = _cells(x1, y1, x2, y2, tol)
    order = np.argsort(bkey, kind="stable")
    bkey, beid = bkey[order], beid[order]
    qkey, qloc = _cells(x1[query], y1[query], x2[query], y2[query], tol)
    qeid = query[qloc]                           # ascending: query is sorted
    lo = np.searchsorted(bkey, qkey, "left")
    cnt = np.searchsorted(bkey, qkey, "right") - lo
    cum = np.cumsum(cnt)
    start = 0
    while start < len(qkey):
        end = int(np.searchsorted(cum, (cum[start - 1] if start else 0) + max_pairs, "right"))
        end = min(max(end, start + 1), len(qkey))
        if end < len(qkey) and qeid[end] == qeid[end - 1]:     # never split one edge's entries
            back = int(np.searchsorted(qeid, qeid[end], "left"))
            end = back if back > start else int(np.searchsorted(qeid, qeid[end], "right"))
        c = cnt[start:end]
        a = np.repeat(qeid[start:end], c)
        pos = np.repeat(lo[start:end], c) + (np.arange(c.sum()) - np.repeat(np.cumsum(c) - c, c))
        b = beid[pos]
        keep = pid[a] != pid[b]
        a, b = a[keep], b[keep]
        if len(a):
            key = np.unique(a * n + b)
            out += _overlap(key // n, key % n, x1, y1, x2, y2, ux, uy, L, tol)
        start = end
    return out


def _overlap(a, b, x1, y1, x2, y2, ux, uy, L, tol) -> np.ndarray:
    """Length of edge ``a`` covered by edge ``b`` (near-parallel, within ``tol``), summed per a."""
    with np.errstate(divide="ignore", invalid="ignore"):
        par = np.abs(ux[a] * uy[b] - uy[a] * ux[b]) <= SIN_HOEK_MAX__0
        a, b = a[par], b[par]
        d1x, d1y = x1[b] - x1[a], y1[b] - y1[a]
        d2x, d2y = x2[b] - x1[a], y2[b] - y1[a]
        s1, n1 = d1x * ux[a] + d1y * uy[a], -d1x * uy[a] + d1y * ux[a]
        s2, n2 = d2x * ux[a] + d2y * uy[a], -d2x * uy[a] + d2y * ux[a]
        dn = n2 - n1
        flat = np.abs(dn) < 1e-9
        t_a, t_b = (-tol - n1) / dn, (tol - n1) / dn
        t_lo = np.clip(np.where(flat, 0.0, np.minimum(t_a, t_b)), 0.0, 1.0)
        t_hi = np.clip(np.where(flat, np.where(np.abs(n1) <= tol, 1.0, 0.0),
                                np.maximum(t_a, t_b)), 0.0, 1.0)
        sa, sb = s1 + (s2 - s1) * t_lo, s1 + (s2 - s1) * t_hi
        ov = np.clip(np.maximum(sa, sb), 0.0, L[a]) - np.clip(np.minimum(sa, sb), 0.0, L[a])
        ov = np.where(t_hi > t_lo, np.maximum(ov, 0.0), 0.0)
    return np.bincount(a, weights=np.nan_to_num(ov), minlength=len(x1))


def exposed_per_sector(pid, x1, y1, x2, y2, n_pand: int, own=None):
    """Exposed wall length per pand and sector: ``(total, side)``, each shape ``(n_pand, 8)``.

    ``own``: boolean per pand; only those get results (the others serve as neighbours only).
    Rows of panden without edges are zero.
    """
    own = np.ones(n_pand, dtype=bool) if own is None else np.asarray(own, dtype=bool)
    L = np.hypot(x2 - x1, y2 - y1)
    query = np.flatnonzero(own[pid] & (L > 1e-6))
    shared = shared_length(pid, x1, y1, x2, y2, query)
    expo = np.clip(L - shared, 0.0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        ux, uy = (x2 - x1) / L, (y2 - y1) / L
    # the building is on the left of (ux, uy): outward = to the right = (uy, -ux)
    az = np.degrees(np.arctan2(uy, -ux)) % 360.0     # compass azimuth of the outward normal
    sector = ((np.nan_to_num(az) + 22.5) // 45).astype(np.int64) % SECTOREN
    # main axis: the direction of the longest edge of each pand
    order = np.lexsort((-L, pid))
    first = np.r_[True, pid[order][1:] != pid[order][:-1]]
    longest = order[first]
    ax, ay = np.zeros(n_pand), np.zeros(n_pand)
    ax[pid[longest]], ay[pid[longest]] = ux[longest], uy[longest]
    side = np.abs(uy * ax[pid] - ux * ay[pid]) <= ZIJ_COS_MAX__0     # |normal . axis|
    sel = query[np.isfinite(az[query]) & (expo[query] > 0)]
    flat = pid[sel] * SECTOREN + sector[sel]
    total = np.bincount(flat, weights=expo[sel], minlength=n_pand * SECTOREN)
    zij = np.bincount(flat, weights=np.where(side[sel], expo[sel], 0.0),
                      minlength=n_pand * SECTOREN)
    return total.reshape(n_pand, SECTOREN), zij.reshape(n_pand, SECTOREN)
