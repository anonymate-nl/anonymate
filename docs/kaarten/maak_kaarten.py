"""Kaarten bij docs/herleidbaarheid-uitleg.md, gemaakt uit echte data.

* Achtergrond: PDOK BRT-Achtergrondkaart, grijs (Kadaster, CC BY 4.0), tegels van
  https://service.pdok.nl/brt/achtergrondkaart/wmts/v2_0/grijs/EPSG:3857/{z}/{x}/{y}.png
* H3-cellen: de h3-bibliotheek (https://h3geo.org), dezelfde die anonymate gebruikt.
* KNMI-stations, woningen en weerzones: de lokale anonymate-populatie (BAG, EP-online), zoals
  ``anonymate build`` die opbouwt.
* Hitte-eiland: RIVM, *Stedelijk hitte-eiland effect (UHI) in Nederland*
  (https://www.atlasleefomgeving.nl/thema/klimaatverandering/kaarten), als woninggewogen
  gemiddelde per PC6: een parquet-bestand met de kolommen ``pc6`` en ``uhi__degC``, via ``--uhi``.

Naast elke PNG een GeoJSON met dezelfde vlakken; GitHub toont die als interactieve kaart.

Gebruik::

    pip install -e ".[kaarten]"
    python docs/kaarten/maak_kaarten.py --uhi PAD/uhi_pc6.parquet
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import contextily as cx
import duckdb
import h3
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402
from matplotlib.colors import Normalize  # noqa: E402
from pyproj import Transformer  # noqa: E402
from shapely.geometry import MultiPoint, Polygon, box, mapping  # noqa: E402
from shapely.ops import transform, voronoi_diagram  # noqa: E402

from anonymate.store import Store  # noqa: E402

HIER = Path(__file__).parent
PDOK = "https://service.pdok.nl/brt/achtergrondkaart/wmts/v2_0/grijs/EPSG:3857/{z}/{x}/{y}.png"
BRON = "Achtergrond: PDOK BRT-Achtergrondkaart (Kadaster, CC BY 4.0)"
CEL = "8419681ffffffff"          # de weerzone in Noord-Holland met de grootste groei door ruis
NL = (3.2, 50.7, 7.3, 53.6)      # lon/lat
KLEUR = "#d7301f"

naar_merc = Transformer.from_crs(4326, 3857, always_xy=True).transform
naar_rd = Transformer.from_crs(4326, 28992, always_xy=True).transform
rd_naar_wgs = Transformer.from_crs(28992, 4326, always_xy=True).transform


def hexagon(cel: str) -> Polygon:
    return Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cel)])


def merc(poly: Polygon) -> np.ndarray:
    return np.asarray(transform(naar_merc, poly).exterior.coords)


def kaart(ax, lonlat_bbox, titel: str) -> None:
    x0, y0 = naar_merc(lonlat_bbox[0], lonlat_bbox[1])
    x1, y1 = naar_merc(lonlat_bbox[2], lonlat_bbox[3])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    cx.add_basemap(ax, source=PDOK, crs="EPSG:3857", attribution=BRON, attribution_size=6)
    ax.set_axis_off()
    ax.set_title(titel, fontsize=10)


def geojson(pad: Path, vlakken: list[tuple[Polygon, dict]]) -> None:
    feats = [{"type": "Feature", "geometry": mapping(p), "properties": props}
             for p, props in vlakken]
    pad.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), "utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--uhi", type=Path, required=True, help="parquet met pc6, uhi__degC")
    args = ap.parse_args()
    store = Store.open()
    pop = store.population_path.as_posix()
    con = duckdb.connect()
    con.execute("SET memory_limit='1GB'")
    eg = "eengezins AND oppervlakte BETWEEN 50 AND 250"

    # --- 1. KNMI-stations: welk gebied ligt het dichtst bij welk station ------------------------
    st = pd.read_parquet(store.raw / "knmi_stations.parquet")
    per_st = con.execute(f"SELECT knmi_station, count(*) n FROM read_parquet('{pop}') "
                         f"WHERE {eg} GROUP BY 1").df()
    st = st.merge(per_st, on="knmi_station")
    rd = [naar_rd(float(lo), float(la)) for la, lo in zip(st["lat"], st["lon"])]
    x0, y0 = naar_rd(NL[0], NL[1])
    x1, y1 = naar_rd(NL[2], NL[3])
    kader = box(x0 - 50_000, y0 - 50_000, x1 + 50_000, y1 + 50_000)
    cellen = voronoi_diagram(MultiPoint(rd), envelope=kader)
    vlakken = []
    for poly in cellen.geoms:
        i = next(j for j, p in enumerate(rd) if poly.contains(MultiPoint([p]).geoms[0]))
        vlakken.append((transform(rd_naar_wgs, poly.intersection(kader)), {
            "station": str(st["knmi_station"].iloc[i]), "naam": st["naam"].iloc[i],
            "eengezinswoningen 50-250 m²": int(st["n"].iloc[i])}))
    geojson(HIER / "knmi_voronoi.geojson", vlakken)
    fig, ax = plt.subplots(figsize=(7, 8))
    kleuren = plt.get_cmap("tab20")(np.arange(len(vlakken)) % 20)
    ax.add_collection(PolyCollection([merc(p) for p, _ in vlakken], facecolors=kleuren,
                                     edgecolors="#333333", linewidths=0.8, alpha=0.35))
    sx, sy = naar_merc(st["lon"].astype(float).to_numpy(), st["lat"].astype(float).to_numpy())
    ax.scatter(sx, sy, s=12, c="black", zorder=3)
    kaart(ax, NL, f"Dichtstbijzijnd KNMI-station: {len(vlakken)} gebieden (Voronoi)")
    fig.savefig(HIER / "knmi_voronoi.png", dpi=110, bbox_inches="tight")
    plt.close(fig)

    # --- 2. H3-cellen niveau 4 ------------------------------------------------------------------
    per_cel = con.execute(f"""SELECT h3_r4, count(*) n, sum(({eg})::int) eg
        FROM read_parquet('{pop}') WHERE h3_r4 IS NOT NULL GROUP BY 1""").df()
    vlakken = [(hexagon(c), {"cel": c, "woningen": int(n),
                             "eengezinswoningen 50-250 m²": int(e)})
               for c, n, e in per_cel.itertuples(index=False)]
    geojson(HIER / "h3_niveau4.geojson", vlakken)
    fig, ax = plt.subplots(figsize=(7, 8))
    ax.add_collection(PolyCollection([merc(p) for p, _ in vlakken], facecolors="#6baed6",
                                     edgecolors="#08519c", linewidths=0.8, alpha=0.25))
    ax.add_collection(PolyCollection([merc(hexagon(CEL))], facecolors=KLEUR,
                                     edgecolors=KLEUR, linewidths=1.2, alpha=0.5))
    kaart(ax, NL, f"H3-cellen niveau 4 met woningen: {len(vlakken)} weerzones")
    fig.savefig(HIER / "h3_niveau4.png", dpi=110, bbox_inches="tight")
    plt.close(fig)

    # --- 3. ruis: de cel en haar buren ----------------------------------------------------------
    ring = list(h3.grid_disk(CEL, 1))
    tel = per_cel.set_index("h3_r4").reindex(ring).fillna(0)
    vlakken = [(hexagon(c), {"cel": c, "rol": "eigen cel" if c == CEL else "buurcel",
                             "woningen": int(tel.loc[c, "n"]),
                             "eengezinswoningen 50-250 m²": int(tel.loc[c, "eg"])})
               for c in ring]
    geojson(HIER / "h3_ruis.geojson", vlakken)
    eigen, alle = int(tel.loc[CEL, "eg"]), int(tel["eg"].sum())
    print(f"ruis: {eigen} -> {alle} eengezinswoningen 50-250 m² ({alle / eigen:.0f}x); "
          f"alle woningen {int(tel.loc[CEL, 'n'])} -> {int(tel['n'].sum())}")
    omlijst = MultiPoint([pt for p, _ in vlakken for pt in p.exterior.coords]).bounds
    marge = 0.05
    bbox = (omlijst[0] - marge, omlijst[1] - marge, omlijst[2] + marge, omlijst[3] + marge)
    fig, axs = plt.subplots(1, 2, figsize=(12, 6.5))
    for ax, met_ruis in zip(axs, (False, True)):
        doel = vlakken if met_ruis else [v for v in vlakken if v[1]["cel"] == CEL]
        ax.add_collection(PolyCollection([merc(p) for p, _ in doel], facecolors=KLEUR,
                                         edgecolors="none", alpha=0.3))
        ax.add_collection(PolyCollection([merc(p) for p, _ in vlakken], facecolors="none",
                                         edgecolors="#555555", linewidths=0.8))
        ax.add_collection(PolyCollection([merc(hexagon(CEL))], facecolors="none",
                                         edgecolors=KLEUR, linewidths=2))
        for p, props in vlakken:
            cx_, cy_ = naar_merc(*np.asarray(p.centroid.coords)[0])
            ax.text(cx_, cy_, f"{props['eengezinswoningen 50-250 m²']:,}".replace(",", "."),
                    ha="center", va="center", fontsize=8,
                    bbox={"boxstyle": "round", "fc": "white", "alpha": 0.7, "lw": 0})
        n = alle if met_ruis else eigen
        kaart(ax, bbox, ("met ruis: de cel en haar buren" if met_ruis else "zonder ruis: "
                         "alleen de eigen cel") + f"\n{n:,} eengezinswoningen".replace(",", "."))
    fig.savefig(HIER / "h3_ruis.png", dpi=110, bbox_inches="tight")
    plt.close(fig)

    # --- 4. hitte-eiland in hetzelfde gebied, fijn en grof afgerond -----------------------------
    w = con.execute(f"""SELECT w.lat, w.lon, u.uhi__degC AS uhi FROM read_parquet('{pop}') w
        JOIN read_parquet('{args.uhi.as_posix()}') u ON u.pc6 = w.postcode6
        WHERE list_contains(?, w.h3_r4) AND w.lat IS NOT NULL""", [ring]).df()
    w["h9"] = [h3.latlng_to_cell(a, b, 9) for a, b in zip(w["lat"], w["lon"])]
    per9 = w.groupby("h9")["uhi"].mean()
    polys = [merc(hexagon(c)) for c in per9.index]
    # ingezoomd op waar de woningen staan; dezelfde kleurschaal in beide panelen
    m = 0.03
    zoom = (w["lon"].min() - m, w["lat"].min() - m, w["lon"].max() + m, w["lat"].max() + m)
    norm = Normalize(0, float(np.ceil(per9.max() * 2) / 2))
    fig, axs = plt.subplots(1, 2, figsize=(11, 8))
    for ax, stap in zip(axs, (0.1, 1.0)):
        waarde = np.floor(per9.to_numpy() / stap + 0.5) * stap
        pc = PolyCollection(polys, array=waarde, cmap="YlOrRd", norm=norm, edgecolors="none",
                            alpha=0.85)
        ax.add_collection(pc)
        ax.add_collection(PolyCollection([merc(p) for p, _ in vlakken], facecolors="none",
                                         edgecolors="#555555", linewidths=0.8))
        ax.add_collection(PolyCollection([merc(hexagon(CEL))], facecolors="none",
                                         edgecolors=KLEUR, linewidths=2))
        kaart(ax, zoom, f"hitte-eiland afgerond op {stap:g} °C: "
                        f"{len(np.unique(waarde))} waarden".replace(".", ","))
    fig.colorbar(pc, ax=axs, shrink=0.5, label="UHI [°C]", orientation="horizontal",
                 pad=0.03)
    fig.savefig(HIER / "uhi_ruisgebied.png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    print("UHI per H3-niveau-9 in het gebied:", len(per9), "vlakjes;",
          "kwantielen", np.round(per9.quantile([0, 0.1, 0.5, 0.9, 1]).to_numpy(), 2))


if __name__ == "__main__":
    main()
