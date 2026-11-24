"""Woningtype uit de BAG-pandcontouren: welke variant komt het best overeen met het energielabel?

Toetst varianten van de buren-afleiding (:mod:`anonymate.gevel`) tegen het woningtype dat de
energieadviseur in EP-online heeft geregistreerd, alleen voor labels volgens NTA 8800 (vanaf 2021).
De varianten verschillen op drie punten:

* **buur** (wie telt als buurpand): ``woon`` = een pand met minstens een woning (AnonyMate en GearUp
  nu); ``vbo`` = een pand met minstens een verblijfsobject, elk gebruiksdoel (Kadaster en CBS);
  ``vbo-overig`` = idem, maar niet een pand met alleen een verblijfsobject "overige gebruiksfunctie",
  zoals een garagebox (Esri);
* **contact** (wanneer zijn twee panden buren): ``muur`` = minstens 2 m gedeelde muur binnen 0,5 m
  (AnonyMate nu); ``raak`` = een gedeelde rand binnen 3 cm, elke lengte (benadering van het
  Kadaster, dat geen tolerantie noemt, en van Esri: 3 cm). Panden die elkaar alleen in een hoekpunt
  raken, tellen bij beide niet; bij het Kadaster waarschijnlijk wel;
* **eengezins** (wanneer is het geen appartement): ``woon`` = het pand heeft precies een woning
  (AnonyMate nu); ``vbo`` = het pand heeft precies een verblijfsobject (Kadaster, CBS, Esri en GearUp).

Hoek of twee-onder-een-kap volgt bij allemaal uit de buur van de buur: heeft die alleen dit pand als
buur, dan twee-onder-een-kap, anders hoekwoning (gelijk aan "een blok van twee" in AnonyMate).

Gebruik::

    python tools/woningtype_varianten.py --ep <ep_online.parquet> --gpkg <bag-light.gpkg> --uit <map>

Schrijft per gebied en variant alleen tellingen (geen adressen of woningen): ``varianten.csv`` met
de kruistabel label x afgeleid type, en ``samenvatting.md``.
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from anonymate.gevel import _per_neighbour, _shared_pairs, edges_from_rings, gpkg_rings
from anonymate.store import LIVE_STATUSES, _PAND_STATUS_BESTAAND, sqlite_readonly_uri

# RD x0, x1, y0, y1 [m]; Zwolle en Leiden zijn de gebieden van de toets van 23-10-2026
GEBIEDEN = {
    "zwolle": (195_000, 210_000, 495_000, 510_000),
    "leiden": (90_000, 105_000, 455_000, 470_000),
    "utrecht-centrum": (133_000, 139_000, 453_000, 459_000),   # oude binnenstad, veel winkels
    "achterhoek": (235_000, 250_000, 440_000, 455_000),        # landelijk, Winterswijk/Groenlo
}
MARGE__m = 300.0          # panden rond het gebied, voor de buren van panden aan de rand
TYPES = ("vrijstaand", "twee_onder_een_kap", "hoekwoning", "tussenwoning", "appartement")

VARIANTEN = {             # naam: (buur, contact, eengezins)
    "anonymate-nu": ("woon", "muur", "woon"),
    "gearup-nu": ("woon", "muur", "vbo"),
    "buur-vbo": ("vbo", "muur", "woon"),
    "buur-vbo-overig": ("vbo-overig", "muur", "woon"),
    "voorstel": ("vbo-overig", "muur", "vbo"),
    "voorstel-met-overig": ("vbo", "muur", "vbo"),
    "kadaster": ("vbo", "raak", "vbo"),
    "esri": ("vbo-overig", "raak", "vbo"),
}
CONTACT = {"muur": (0.5, 2.0), "raak": (0.03, 1e-6)}     # tolerantie [m], minimale lengte [m]


def lees_gebied(con: sqlite3.Connection, box) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Panden (met contour) en verblijfsobjecten in het gebied plus de marge."""
    x0, x1, y0, y1 = box[0] - MARGE__m, box[1] + MARGE__m, box[2] - MARGE__m, box[3] + MARGE__m
    panden = pd.DataFrame(con.execute(
        "SELECT p.identificatie, p.status, p.geom, p.aantal_verblijfsobjecten FROM pand p "
        "JOIN rtree_pand_geom r ON p.feature_id = r.id "
        "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ?",
        (x0, x1, y0, y1)).fetchall(), columns=["pand", "status", "geom", "pdok_vbo"])
    vbo = pd.DataFrame(con.execute(
        "SELECT v.identificatie, v.status, v.gebruiksdoel, v.pand_identificatie, r.minx, r.miny "
        "FROM verblijfsobject v JOIN rtree_verblijfsobject_geom r ON v.feature_id = r.id "
        "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ?",
        (x0, x1, y0, y1)).fetchall(), columns=["vbo", "status", "doel", "pand", "x", "y"])
    panden = panden[panden.status.isin(_PAND_STATUS_BESTAAND)].drop_duplicates("pand")
    vbo = vbo[vbo.status.isin(LIVE_STATUSES)].drop_duplicates(["vbo", "pand"])
    return panden.reset_index(drop=True), vbo.reset_index(drop=True)


def paren(panden: pd.DataFrame, tol: float) -> pd.DataFrame:
    """Gedeelde randlengte per paar panden (beide richtingen), bij tolerantie ``tol``."""
    rings = [gpkg_rings(g) for g in panden.geom]
    pid, x1, y1, x2, y2 = edges_from_rings(rings)
    L = np.hypot(x2 - x1, y2 - y1)
    query = np.flatnonzero(L > 1e-6)
    parts = list(_shared_pairs(pid, x1, y1, x2, y2, query, tol=tol, max_pairs=4_000_000))
    a, b, ov = (np.concatenate([p[i] for p in parts]) if parts
                else np.zeros(0, dtype=np.int64 if i < 2 else float) for i in range(3))
    pa_, pb_, length = _per_neighbour(pid, a, b, ov)
    df = pd.DataFrame({"a": pa_, "b": pb_, "lengte": length})
    # each direction measured from its own edges; a pair counts with the longer of the two
    df = pd.concat([df, df.rename(columns={"a": "b", "b": "a"})])
    return df.groupby(["a", "b"], as_index=False).lengte.max()


def typeer(panden: pd.DataFrame, pairs: pd.DataFrame, min_len: float, buur: str,
           eengezins: str) -> np.ndarray:
    """Woningtype per pand (index als in ``panden``) voor een variant; None waar geen woning."""
    if buur == "woon":
        ok = panden.n_woon.to_numpy() > 0
    elif buur == "vbo":
        ok = panden.n_vbo.to_numpy() > 0
    else:
        ok = (panden.n_vbo.to_numpy() > 0) & ~panden.alleen_overig.to_numpy()
    p = pairs[(pairs.lengte >= min_len)]
    p = p[ok[p.a.to_numpy()] & ok[p.b.to_numpy()]]
    deg = np.bincount(p.a.to_numpy(), minlength=len(panden))
    # the one neighbour of panden with exactly one
    one = p[deg[p.a.to_numpy()] == 1]
    buur_van = np.full(len(panden), -1)
    buur_van[one.a.to_numpy()] = one.b.to_numpy()
    single = (panden.n_woon.to_numpy() == 1 if eengezins == "woon"
              else (panden.n_vbo.to_numpy() == 1) & (panden.n_woon.to_numpy() == 1))
    out = np.full(len(panden), None, dtype=object)
    has_home = panden.n_woon.to_numpy() > 0
    out[has_home & ~single] = "appartement"
    s = has_home & single
    out[s & (deg == 0)] = "vrijstaand"
    out[s & (deg >= 2)] = "tussenwoning"
    q = buur_van[s & (deg == 1)]
    out[np.flatnonzero(s & (deg == 1))] = np.where(deg[q] == 1, "twee_onder_een_kap", "hoekwoning")
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--ep", required=True, help="ep_online.parquet (met de herstelde normalisatie)")
    ap.add_argument("--gpkg", required=True, help="bag-light.gpkg")
    ap.add_argument("--uit", required=True, help="map voor de uitkomsten")
    ap.add_argument("--gebied", nargs="*", default=list(GEBIEDEN))
    args = ap.parse_args(argv)
    uit = Path(args.uit)
    uit.mkdir(parents=True, exist_ok=True)
    ep = duckdb.connect().execute(
        f"SELECT vbo_id AS vbo, woningtype AS label, nta8800 FROM read_parquet('{Path(args.ep).as_posix()}') "
        "WHERE woningtype IS NOT NULL").df()
    uri = sqlite_readonly_uri(Path(args.gpkg))
    con = sqlite3.connect(uri, uri=True)
    rows, klaar = [], []
    for naam in args.gebied:
        t = time.time()
        box = GEBIEDEN[naam]
        deel = uit / f"varianten-{naam}.csv"
        if deel.exists():              # done in an earlier run that stopped later on
            klaar.append(pd.read_csv(deel))
            print(f"{naam}: uit {deel.name}", flush=True)
            continue
        cache_p, cache_v = uit / f"bag-{naam}-panden.parquet", uit / f"bag-{naam}-vbo.parquet"
        for poging in range(10):
            try:
                if cache_p.exists() and cache_v.exists():   # local copy of an earlier read
                    panden, vbo = pd.read_parquet(cache_p), pd.read_parquet(cache_v)
                else:
                    panden, vbo = lees_gebied(con, box)
                    panden.to_parquet(cache_p), vbo.to_parquet(cache_v)
                break
            except sqlite3.OperationalError as e:
                # a GeoPackage on a NAS can drop out for a moment (as in store.ingest_bag_gevel)
                if "i/o" not in str(e).lower() or poging == 9:
                    raise
                print(f"  leesfout ({e}), opnieuw over 30 s", flush=True)
                time.sleep(30)
                con.close()
                con = sqlite3.connect(uri, uri=True)
        start = len(rows)
        idx = pd.Series(np.arange(len(panden)), index=panden.pand)
        vbo = vbo[vbo.pand.isin(idx.index)].copy()
        vbo["woon"] = vbo.doel.fillna("").str.contains("woonfunctie")
        per = vbo.groupby("pand").agg(n_vbo=("vbo", "nunique"), n_woon=("woon", "sum"),
                                       doelen=("doel", lambda s: set(s.fillna(""))))
        panden = panden.join(per, on="pand")
        panden[["n_vbo", "n_woon"]] = panden[["n_vbo", "n_woon"]].fillna(0).astype(int)
        panden["alleen_overig"] = (panden.n_vbo == 1) & panden.doelen.apply(
            lambda d: isinstance(d, set) and d == {"overige gebruiksfunctie"})
        pairs = {c: paren(panden, tol) for c, (tol, _) in CONTACT.items()}
        # the dwellings inside the area (not the margin) with a label
        binnen = vbo[vbo.woon & vbo.x.between(box[0], box[1]) & vbo.y.between(box[2], box[3])]
        # a dwelling in several panden: Kadaster leaves it untyped when they differ; here the
        # first pand, and the count is reported
        meer = binnen.groupby("vbo").pand.nunique()
        binnen = binnen.drop_duplicates("vbo").merge(ep, on="vbo")
        print(f"{naam}: {len(panden):,} panden, {len(binnen):,} woningen met label "
              f"({int(binnen.nta8800.sum()):,} NTA 8800), {int((meer > 1).sum())} woningen in "
              f"meer panden", flush=True)
        for var, (buur, contact, eg) in VARIANTEN.items():
            typ = typeer(panden, pairs[contact], CONTACT[contact][1], buur, eg)
            afgeleid = typ[idx[binnen.pand].to_numpy()]
            tab = pd.DataFrame({"label": binnen.label.to_numpy(), "afgeleid": afgeleid,
                                "nta8800": binnen.nta8800.to_numpy()})
            tab["afgeleid"] = tab.afgeleid.fillna("onbekend")
            for (lab, af, nta), n in tab.groupby(["label", "afgeleid", "nta8800"]).size().items():
                rows.append({"gebied": naam, "variant": var, "nta8800": bool(nta), "label": lab,
                             "afgeleid": af, "aantal": int(n)})
        pd.DataFrame(rows[start:]).to_csv(deel, index=False)
        print(f"  {round(time.time() - t)} s", flush=True)
    df = pd.concat(klaar + [pd.DataFrame(rows)], ignore_index=True)
    df.to_csv(uit / "varianten.csv", index=False)
    (uit / "samenvatting.md").write_text(samenvatting(df), encoding="utf-8")
    print(samenvatting(df))


def samenvatting(df: pd.DataFrame) -> str:
    """Per variant: aandeel juist, per labeltype (recall) en totaal, NTA 8800-labels."""
    d = df[df.nta8800]
    out = []
    for scope, sel in (("alle woningen", d), ("eengezins volgens label", d[d.label != "appartement"])):
        tot = sel.groupby("variant").aantal.sum()
        goed = sel[sel.label == sel.afgeleid].groupby("variant").aantal.sum()
        per = sel.groupby(["variant", "label"]).aantal.sum()
        per_goed = sel[sel.label == sel.afgeleid].groupby(["variant", "label"]).aantal.sum()
        rec = (per_goed / per).unstack().reindex(columns=[t for t in TYPES if t in sel.label.unique()])
        tabel = pd.concat([(goed / tot).rename("totaal"), rec], axis=1).reindex(list(VARIANTEN))
        out.append(f"## {scope} (NTA 8800-labels; n = {int(tot.iloc[0]):,})\n")
        out.append(_md(tabel))
        out.append("")
    gebieden = d.groupby(["gebied", "variant"]).apply(
        lambda s: s[s.label == s.afgeleid].aantal.sum() / s.aantal.sum()).unstack(0)
    out.append("## Per gebied, alle woningen (aandeel juist)\n")
    out.append(_md(gebieden.reindex(list(VARIANTEN))))
    return "\n".join(out) + "\n"


def _md(t: pd.DataFrame) -> str:
    """Een tabel met aandelen als Markdown (zonder tabulate)."""
    kop = "| variant | " + " | ".join(str(c) for c in t.columns) + " |"
    lijn = "|---|" + "---:|" * len(t.columns)
    regels = ["| " + str(i) + " | " + " | ".join("" if pd.isna(v) else f"{v:.1%}" for v in r) + " |"
              for i, r in zip(t.index, t.to_numpy())]
    return "\n".join([kop, lijn, *regels])


if __name__ == "__main__":
    main()
