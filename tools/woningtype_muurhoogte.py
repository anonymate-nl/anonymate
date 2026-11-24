"""Woningtype uit de BAG-pandcontouren, met de hoogte van de gedeelde muur uit 3DBAG.

Vervolg op ``tools/woningtype_varianten.py``. Daar bleek de grootste fout dat twee-onder-een-kappen
die via hun garages aan elkaar vastzitten, als tussenwoning uitkomen. Hier telt een buur alleen
mee als minstens 2 m van de gedeelde muur hoger is dan een drempel ``H``. Die hoogte komt uit de
LoD1.3-delen van 3DBAG (``lod13_2d``: elk deel van een pand met een eigen dakhoogte): per punt
op de gedeelde muur (om de meter) de 70e-percentielhoogte van het dichtstbijzijnde deel van elk
van beide panden, min het maaiveld van dat pand. De muur is zo hoog als het laagste van de twee.
Ontbreekt een hoogte (pand niet in 3DBAG, of geen deel in de buurt), dan telt dat stuk als hoog:
zonder 3DBAG doet de regel hetzelfde als nu.

Gebruik::

    python tools/woningtype_muurhoogte.py --ep <ep_online.parquet> --uit <map van de varianten>
        --tegels <3dbag-tegels.parquet> --tegelmap <map met de .gpkg.gz-tegels>

``--uit`` is de map van ``woningtype_varianten.py``: daar staan de BAG-gegevens per gebied
(``bag-<gebied>-*.parquet``). De 3DBAG-delen per gebied komen erbij (``3dbag-<gebied>.parquet``).
``--tegels`` is de tegelindex (tile_id en rechthoek in RD). Schrijft alleen tellingen:
``muurhoogte.csv`` en ``muurhoogte.md``.
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import shapely

sys.path.insert(0, str(Path(__file__).parent))
from woningtype_varianten import CONTACT, GEBIEDEN, MARGE__m, TYPES, _md, typeer  # noqa: E402

from anonymate.gevel import _shared_pairs, edges_from_rings, gpkg_rings  # noqa: E402

DREMPELS__m = (0.0, 3.5, 4.0, 4.5, 5.0)       # 0 = geen hoogte-eis (de regel van nu)
STAP__m = 1.0                                  # afstand tussen de meetpunten op de muur
ZOEK__m = 1.0                                  # hoe ver een LoD1.3-deel van het meetpunt mag liggen
BASIS = {"anonymate-nu": ("woon", "woon"), "voorstel": ("vbo-overig", "vbo")}   # (buur, eengezins)


def lees_3dbag(tegels: pd.DataFrame, tegelmap: Path, box, werk: Path) -> pd.DataFrame:
    """LoD1.3-delen (pand, hoogte boven maaiveld, contour als WKB) uit de tegels rond ``box``."""
    x0, x1, y0, y1 = box[0] - MARGE__m, box[1] + MARGE__m, box[2] - MARGE__m, box[3] + MARGE__m
    sel = tegels[(tegels.x1 >= x0) & (tegels.x0 <= x1) & (tegels.y1 >= y0) & (tegels.y0 <= y1)]
    frames = []
    for i, tid in enumerate(sel.tile_id):
        bron = tegelmap / (tid.replace("/", "-") + ".gpkg.gz")
        if not bron.exists():
            print(f"  tegel {tid} ontbreekt", flush=True)
            continue
        doel = werk / "tegel.gpkg"
        with gzip.open(bron, "rb") as f, open(doel, "wb") as g:
            shutil.copyfileobj(f, g)
        con = sqlite3.connect(doel)
        try:
            d = pd.read_sql_query(
                "SELECT l.identificatie AS pand, l.b3_h_70p - p.b3_h_maaiveld AS hoogte, l.geom "
                "FROM lod13_2d l JOIN pand p ON p.identificatie = l.identificatie", con)
        finally:
            con.close()
        frames.append(d)
        if (i + 1) % 25 == 0:
            print(f"  {i + 1}/{len(sel)} tegels", flush=True)
    d = pd.concat(frames, ignore_index=True)
    d["pand"] = d.pand.str.extract(r"(\d{16})$")[0]
    # a part as plain WKB (polygon rings from the GeoPackage blob)
    d["wkb"] = [shapely.to_wkb(_poly(gpkg_rings(g))) for g in d.geom]
    return d.drop(columns="geom").drop_duplicates(["pand", "wkb"])


def _poly(rings):
    outer = [r for r, hole in rings if not hole]
    holes = [r for r, hole in rings if hole]
    if not outer:
        return shapely.Polygon()
    if len(outer) == 1:
        return shapely.Polygon(outer[0], holes)
    return shapely.MultiPolygon([shapely.Polygon(r) for r in outer])


def muurparen(panden: pd.DataFrame, delen: pd.DataFrame, tol: float) -> pd.DataFrame:
    """Per paar panden: de gedeelde muurlengte en de hoogte van die muur, als meetpunten om de
    meter (``a``, ``b``, ``lengte`` per punt, ``hoogte`` per punt; NaN = onbekend)."""
    rings = [gpkg_rings(g) for g in panden.geom]
    pid, x1, y1, x2, y2 = edges_from_rings(rings)
    L = np.hypot(x2 - x1, y2 - y1)
    query = np.flatnonzero(L > 1e-6)
    parts = list(_shared_pairs(pid, x1, y1, x2, y2, query, tol=tol, max_pairs=4_000_000))
    a = np.concatenate([p[0] for p in parts])
    b = np.concatenate([p[1] for p in parts])
    keep = np.concatenate([p[2] for p in parts]) > 0
    a, b = a[keep], b[keep]
    # the covered stretch of edge a, as in gevel._overlap (without the tolerance band: the
    # projection of edge b onto edge a is close enough for where the wall is)
    ux, uy = (x2[a] - x1[a]) / L[a], (y2[a] - y1[a]) / L[a]
    s1 = (x1[b] - x1[a]) * ux + (y1[b] - y1[a]) * uy
    s2 = (x2[b] - x1[a]) * ux + (y2[b] - y1[a]) * uy
    lo = np.clip(np.minimum(s1, s2), 0, L[a])
    hi = np.clip(np.maximum(s1, s2), 0, L[a])
    ok = hi > lo
    a, b, lo, hi, ux, uy = a[ok], b[ok], lo[ok], hi[ok], ux[ok], uy[ok]
    n = np.maximum(1, np.round((hi - lo) / STAP__m).astype(int))
    r = np.repeat(np.arange(len(a)), n)
    k = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
    s = lo[r] + (k + 0.5) * ((hi - lo) / n)[r]
    px, py = x1[a][r] + s * ux[r], y1[a][r] + s * uy[r]
    punten = pd.DataFrame({"a": pid[a][r], "b": pid[b][r], "lengte": ((hi - lo) / n)[r],
                           "x": px, "y": py})
    # height per point and side: the nearest LoD1.3 part of that same pand
    idx = pd.Series(np.arange(len(panden)), index=panden.pand.to_numpy())
    delen = delen[delen.pand.isin(idx.index)]
    dpand = idx[delen.pand].to_numpy()
    geoms = shapely.from_wkb(delen.wkb.to_numpy())
    tree = shapely.STRtree(geoms)
    pts = shapely.points(punten.x.to_numpy(), punten.y.to_numpy())
    for kant in ("a", "b"):
        qi, di = tree.query(pts, predicate="dwithin", distance=ZOEK__m)
        same = dpand[di] == punten[kant].to_numpy()[qi]
        qi, di = qi[same], di[same]
        afst = shapely.distance(pts[qi], geoms[di])
        t = pd.DataFrame({"p": qi, "afst": afst, "h": delen.hoogte.to_numpy()[di]})
        t = t.sort_values(["p", "afst"]).drop_duplicates("p")
        h = np.full(len(punten), np.nan)
        h[t.p.to_numpy()] = t.h.to_numpy()
        punten[f"h_{kant}"] = h
    punten["hoogte"] = punten[["h_a", "h_b"]].min(axis=1, skipna=False)
    return punten[["a", "b", "lengte", "hoogte"]]


def paren_boven(punten: pd.DataFrame, drempel: float) -> pd.DataFrame:
    """Gedeelde muurlengte per paar (beide richtingen), alleen waar de muur ≥ ``drempel`` is."""
    p = punten[punten.hoogte.isna() | (punten.hoogte >= drempel)] if drempel > 0 else punten
    df = p.groupby(["a", "b"], as_index=False).lengte.sum()
    df = pd.concat([df, df.rename(columns={"a": "b", "b": "a"})])
    return df.groupby(["a", "b"], as_index=False).lengte.max()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ep", required=True)
    ap.add_argument("--uit", required=True)
    ap.add_argument("--tegels", required=True)
    ap.add_argument("--tegelmap", required=True)
    ap.add_argument("--gebied", nargs="*", default=list(GEBIEDEN))
    args = ap.parse_args(argv)
    uit = Path(args.uit)
    tegels = pd.read_parquet(args.tegels)
    ep = duckdb.connect().execute(
        f"SELECT vbo_id AS vbo, woningtype AS label, nta8800 FROM "
        f"read_parquet('{Path(args.ep).as_posix()}') WHERE woningtype IS NOT NULL AND nta8800").df()
    tol, min_len = CONTACT["muur"]
    rows, dekking = [], []
    for naam in args.gebied:
        t = time.time()
        box = GEBIEDEN[naam]
        panden = pd.read_parquet(uit / f"bag-{naam}-panden.parquet")
        vbo = pd.read_parquet(uit / f"bag-{naam}-vbo.parquet")
        cache = uit / f"3dbag-{naam}.parquet"
        if cache.exists():
            delen = pd.read_parquet(cache)
        else:
            with tempfile.TemporaryDirectory() as werk:
                delen = lees_3dbag(tegels, Path(args.tegelmap), box, Path(werk))
            delen.to_parquet(cache)
        idx = pd.Series(np.arange(len(panden)), index=panden.pand)
        vbo = vbo[vbo.pand.isin(idx.index)].copy()
        vbo["woon"] = vbo.doel.fillna("").str.contains("woonfunctie")
        per = vbo.groupby("pand").agg(n_vbo=("vbo", "nunique"), n_woon=("woon", "sum"),
                                       doelen=("doel", lambda s: set(s.fillna(""))))
        panden = panden.join(per, on="pand")
        panden[["n_vbo", "n_woon"]] = panden[["n_vbo", "n_woon"]].fillna(0).astype(int)
        panden["alleen_overig"] = (panden.n_vbo == 1) & panden.doelen.apply(
            lambda d: isinstance(d, set) and d == {"overige gebruiksfunctie"})
        punten = muurparen(panden, delen, tol)
        bekend = punten.hoogte.notna()
        dekking.append({"gebied": naam, "muur_m": punten.lengte.sum(),
                        "met_hoogte": punten.lengte[bekend].sum()})
        binnen = vbo[vbo.woon & vbo.x.between(box[0], box[1]) & vbo.y.between(box[2], box[3])]
        binnen = binnen.drop_duplicates("vbo").merge(ep, on="vbo")
        print(f"{naam}: {len(delen):,} LoD1.3-delen, hoogte bekend voor "
              f"{punten.lengte[bekend].sum() / punten.lengte.sum():.1%} van de gedeelde muur, "
              f"{len(binnen):,} woningen met NTA 8800-label", flush=True)
        for h in DREMPELS__m:
            pairs = paren_boven(punten, h)
            for basis, (buur, eg) in BASIS.items():
                typ = typeer(panden, pairs, min_len, buur, eg)
                af = pd.Series(typ[idx[binnen.pand].to_numpy()]).fillna("onbekend")
                tab = pd.DataFrame({"label": binnen.label.to_numpy(), "afgeleid": af.to_numpy()})
                for (lab, a), n in tab.groupby(["label", "afgeleid"]).size().items():
                    rows.append({"gebied": naam, "variant": f"{basis} H>={h:g}", "label": lab,
                                 "afgeleid": a, "aantal": int(n)})
        print(f"  {round(time.time() - t)} s", flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(uit / "muurhoogte.csv", index=False)
    tekst = samenvatting(df, pd.DataFrame(dekking))
    (uit / "muurhoogte.md").write_text(tekst, encoding="utf-8")
    print(tekst)


def samenvatting(df: pd.DataFrame, dekking: pd.DataFrame) -> str:
    out = []
    volgorde = list(dict.fromkeys(df.variant))
    for scope, sel in (("alle woningen", df), ("eengezins volgens label", df[df.label != "appartement"])):
        tot = sel.groupby("variant").aantal.sum()
        goed = sel[sel.label == sel.afgeleid].groupby("variant").aantal.sum()
        per = sel.groupby(["variant", "label"]).aantal.sum()
        per_goed = sel[sel.label == sel.afgeleid].groupby(["variant", "label"]).aantal.sum()
        rec = (per_goed / per).unstack().reindex(columns=[t for t in TYPES if t in sel.label.unique()])
        tabel = pd.concat([(goed / tot).rename("totaal"), rec], axis=1).reindex(volgorde)
        out += [f"## {scope} (NTA 8800-labels; n = {int(tot.iloc[0]):,})\n", _md(tabel), ""]
    # where the semi-detached labels go
    s = df[df.label == "twee_onder_een_kap"].groupby(["variant", "afgeleid"]).aantal.sum().unstack()
    s = s.div(s.sum(axis=1), axis=0).reindex(volgorde)
    out += ["## Label twee-onder-een-kap: afgeleid als\n", _md(s), ""]
    gebieden = df.groupby(["gebied", "variant"]).apply(
        lambda s: s[s.label == s.afgeleid].aantal.sum() / s.aantal.sum()).unstack(0)
    out += ["## Per gebied, alle woningen (aandeel juist)\n", _md(gebieden.reindex(volgorde)), ""]
    dekking["aandeel"] = dekking.met_hoogte / dekking.muur_m
    out.append("Gedeelde muur met een hoogte uit 3DBAG: " + ", ".join(
        f"{r.gebied} {r.aandeel:.1%}" for r in dekking.itertuples()))
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
