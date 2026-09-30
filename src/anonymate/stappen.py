"""The steps of the desktop window as plain functions: data in, data out, without Qt.

What the window used to work out inside its widgets is here, so that the Windows app and the
browser version (:mod:`anonymate.web`) show the same numbers and the same Dutch texts: guessing
the link and GPS columns, the location per dwelling, the weather location (H3 cell after noise,
or KNMI station), the urban heat island (UHI), putting a traced weather series back into the
dataset, the region, the texts of a map cell and of a dwelling, the classes of the k histogram,
the representativeness lines and readable error messages. No network and no local store
(``tests/test_stappen.py`` guards that).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pandas as pd

from .invoer import _scope_from_args, parse_scope
from .kaart import available, noisy_cells
from .population import Population
from .qids import CATALOGUE
from .risk import Status
from .tabel import lees_parquet

WEATHER_H3 = "weerzone_h3"
WEATHER_STATION = "weer_knmi_station"
UHI = "uhi"

STATUS_TEXT = {Status.OK: "publiceerbaar", Status.AT_RISK: "te herleidbaar",
               Status.NO_MATCH: "geen match"}

# GPS columns by whole word: 'installatiedatum' holds 'lat', 'salon' holds 'lon'
GPS_LAT = r"(^|[^a-z])(lat|latitude|breedte|breedtegraad)([^a-z]|$)"
GPS_LON = r"(^|[^a-z])(lon|lng|long|longitude|lengte|lengtegraad)([^a-z]|$)"


def nl(x: float, digits: int = 1) -> str:
    """A number with a decimal comma."""
    return f"{x:.{digits}f}".replace(".", ",")


def nr(x: float) -> str:
    """A whole number with dots between the thousands."""
    return f"{x:,.0f}".replace(",", ".")


def html(text: str) -> str:
    """Our small markup as HTML: ``**bold**`` and ``!!bold orange!!``."""
    text = re.sub(r"!!(.+?)!!", r"<span style='color:#C05A12'><b>\1</b></span>", text)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)


def plain(text: str) -> str:
    """The same text without the markup."""
    return re.sub(r"(\*\*|!!)", "", text)


# --- columns ------------------------------------------------------------------------------------
def link_columns(found) -> list[str]:
    """Columns that point at the address: a BAG-ID, or postcode plus house number (plus letter
    and addition when present), as detection found them."""
    names = [d.column for d in found]
    bag = next((c for c in names if re.search(r"(^|_)(vbo|verblijfsobject|bag)_?id(_|$)",
                                               c, re.I)), None)
    if bag:
        return [bag]
    pc = next((d.column for d in found if d.qid == "postcode6"), None)
    nr_ = next((c for c in names if re.fullmatch(r"huis_?nummer|huisnr|house_?number|nr",
                                                 c, re.I)), None)
    if not (pc and nr_):
        return []
    letter = next((c for c in names if re.fullmatch(r"huis_?letter|letter", c, re.I)), None)
    extra = next((c for c in names if re.fullmatch(r"toevoeging|huisnummer_?toevoeging|"
                                                   r"addition", c, re.I)), None)
    return [pc, nr_] + ([letter] if letter else []) + ([extra] if extra and letter else [])


# a number as the tables write it: 1.234 (dot for thousands), 0,35 (decimal comma), 3.5, 1e-05,
# with an optional sign, a percent sign or the 'k' of thousands
_NUMBER = re.compile(r"^[-+−]?(\d{1,3}(\.\d{3})+(,\d+)?|\d+([.,]\d+)?)([eE][-+]?\d+)?\s*(%|k)?$")


def numeric_column(values) -> bool:
    """Whether a table column holds numbers: it has at least one value, and every value that is
    not empty is a number, as a Python number or as text ("1.234", "0,35", "12k", "45%").
    Such a column is right-aligned, header included (the Windows window and the browser)."""
    seen = False
    for v in values:
        if v is None or (isinstance(v, float) and math.isnan(v)):
            continue
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float)):
            seen = True
            continue
        text = str(v).strip()
        if not text:
            continue
        if not _NUMBER.match(text):
            return False
        seen = True
    return seen


def numeric_flags(rows, n_columns: int) -> list[bool]:
    """:func:`numeric_column` for every column of ``rows`` (a list of rows)."""
    return [numeric_column(r[j] for r in rows if j < len(r)) for j in range(n_columns)]


def target_label(share: float | None = None) -> str:
    """The label at the orange dashed line of the trade-off chart (``generalize.TARGET_SHARE``)."""
    from .generalize import TARGET_SHARE      # lazy: the browser version loads it with the search
    share = TARGET_SHARE if share is None else share
    return f"doel zoektocht: {share:.0%} publiceerbaar"


def target_note(share: float | None = None) -> str:
    """What that line means, one sentence under the chart and in its tooltip."""
    from .generalize import TARGET_SHARE
    share = TARGET_SHARE if share is None else share
    return (f"De zoektocht stopt zodra {share:.0%} van de woningen publiceerbaar is; daarna kost "
            "elke stap vooral informatie.")


def numeric_columns(df: pd.DataFrame) -> list[str]:
    """Columns that hold numbers (more than 90% of the values): candidates for GPS columns."""
    return [c for c in df.columns
            if pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.9]


def guess_gps(columns) -> tuple[str, str]:
    """(latitude column, longitude column) among ``columns``, by whole word; '' when unknown."""
    columns = list(columns)
    lat = next((c for c in columns if re.search(GPS_LAT, c, re.I)), "")
    lon = next((c for c in columns if re.search(GPS_LON, c, re.I)), "")
    return lat, lon


def link_kwargs(cols, columns) -> dict:
    """The arguments of :func:`anonymate.link.link` from the chosen link columns (a list, or the
    text with commas); ``columns`` are the dataset's columns."""
    if isinstance(cols, str):
        cols = cols.split(",")
    cols = [c.strip() for c in cols if c and c.strip()]
    if not cols:
        raise ValueError("Deze stap heeft het adres nodig, maar de koppelkolommen zijn leeg. "
                         "Vul in stap 4 bij 'koppelkolommen' postcode,huisnummer of een "
                         "BAG-ID-kolom in, of zet de signatuur (stap 4) en de weerlocatie "
                         "(stap 5) uit.")
    missing = [c for c in cols if c not in columns]
    if missing:
        raise ValueError(f"koppelkolommen niet in de dataset: {', '.join(missing)}")
    if len(cols) == 1:
        return {"vbo_id": cols[0]}
    return dict(zip(["postcode", "huisnummer", "huisletter", "toevoeging"], cols))


# --- the dwellings and the norm ----------------------------------------------------------------
# classes of the k histogram: (lowest, highest) number of look-alikes; the first is cut at the norm
K_EDGES = [(0, 10), (11, 30), (31, 100), (101, 300), (301, 1000), (1001, math.inf)]


def houses_for(k: float, norm_k: int, cap: int = 20) -> tuple[int, int, int]:
    """(filled, total, more) for a row of houses showing k dwellings against the norm."""
    k = 0 if k is None or (isinstance(k, float) and math.isnan(k)) else int(k)
    total = max(norm_k, min(k, cap))
    filled = min(k, total)
    return filled, total, max(k - total, 0)


def k_histogram(ks, norm_k: int) -> list[tuple[float, float, int]]:
    """The classes of the k histogram as (lowest, highest, records): the first is everything
    below the norm, the rest are :data:`K_EDGES` from the norm up."""
    ks = [0 if k is None or (isinstance(k, float) and math.isnan(k)) else k for k in ks]
    edges = [(0, norm_k - 1)] + [(max(a, norm_k), b) for a, b in K_EDGES[1:] if b >= norm_k]
    return [(a, b, sum(1 for k in ks if a <= k <= b)) for a, b in edges]


# --- the weather location -----------------------------------------------------------------------
def locations(df: pd.DataFrame, population: Population, *, source: str = "koppel",
              link_cols=None, gps: tuple[str, str] | None = None) -> pd.DataFrame:
    """lat, lon (and postcode6 when linked) per record. ``source`` is "gps" (with ``gps`` the
    two columns) or "koppel" (the dwelling is found in the population through ``link_cols``)."""
    if source == "gps":
        la, lo = gps or ("", "")
        if not la or not lo:
            raise ValueError("kies de GPS-kolommen (breedte- en lengtegraad)")
        return pd.DataFrame({"lat": pd.to_numeric(df[la], errors="coerce"),
                             "lon": pd.to_numeric(df[lo], errors="coerce"),
                             "postcode6": None}, index=df.index)
    from .link import link
    if not available(population):
        raise ValueError("Een weerlocatie via het adres vraagt een populatie met "
                         "coördinaten; bouw de populatie op ('anonymate build'), of kies "
                         "GPS als bron.")
    linked = link(df, population, **link_kwargs(link_cols, df.columns))
    ids = linked["register_vbo_id"].astype(str).tolist()
    lat = population.lookup("lat", "vbo_id", ids)
    lon = population.lookup("lon", "vbo_id", ids)
    pc6 = population.lookup("postcode6", "vbo_id", ids)
    return pd.DataFrame({"lat": [float(lat[v]) if v in lat else math.nan for v in ids],
                         "lon": [float(lon[v]) if v in lon else math.nan for v in ids],
                         "postcode6": [pc6.get(v) for v in ids]}, index=df.index)


_locations = locations


def add_weather(df: pd.DataFrame, population: Population, *, method: str | None,
                level: int = 5, sigma: float = 10.0, seed: int = 0, count_noise: bool = True,
                locations: pd.DataFrame | None = None, source: str = "koppel",
                link_cols=None, gps: tuple[str, str] | None = None
                ) -> tuple[pd.DataFrame, dict[str, str], float | None]:
    """The dataset with a weather location as published column, without an older weather or UHI
    column: ``method`` "h3" (the H3 cell of ``level`` after noise of ``sigma`` km per axis, drawn
    with ``seed``) or "knmi" (the nearest KNMI station, through the link columns); None only
    clears the old columns. ``locations`` (see :func:`locations`) is worked out when not given.

    Returns (new dataframe, {added column: qid key}, tolerance in km), the tolerance being what
    the attacker's search must allow for (sigma when the noise counts, else 0), or None when
    no weather column was added."""
    loc = locations if locations is not None else _locations(
        df, population, source=source, link_cols=link_cols, gps=gps)
    out = df.drop(columns=[c for c in (WEATHER_H3, WEATHER_STATION, UHI) if c in df.columns])
    added: dict[str, str] = {}
    tolerance = None
    if method == "h3":
        out[WEATHER_H3] = noisy_cells(loc["lat"], loc["lon"], level, float(sigma), seed)
        added[WEATHER_H3] = "h3_cel"
        tolerance = float(sigma) if count_noise else 0.0
    elif method == "knmi":
        if "knmi_station" not in population.columns:
            raise ValueError("de populatie kent geen KNMI-stations")
        from .link import link
        if source == "gps":
            raise ValueError("KNMI-station vanuit GPS: kies de koppelkolommen als bron")
        linked = link(df, population, **link_kwargs(link_cols, df.columns))
        ids = linked["register_vbo_id"].astype(str).tolist()
        st = population.lookup("knmi_station", "vbo_id", ids)
        out[WEATHER_STATION] = [st.get(v) for v in ids]
        added[WEATHER_STATION] = "knmi_station"
        tolerance = 0.0
    return out, added, tolerance


# --- the urban heat island ----------------------------------------------------------------------
def uhi_table(frame: pd.DataFrame) -> dict:
    """postcode6 -> UHI [°C] from a table with a postcode and a UHI column."""
    pc = next((c for c in frame.columns if c.lower() in ("pc6", "postcode6", "postcode")), None)
    val = next((c for c in frame.columns if c.lower().startswith("uhi")), None)
    if pc is None or val is None:
        raise ValueError("het UHI-bestand heeft een kolom pc6 (of postcode6) en uhi nodig")
    keys = frame[pc].astype(str).str.replace(" ", "").str.upper()
    return dict(zip(keys, pd.to_numeric(frame[val], errors="coerce")))


def read_uhi_frame(path: str) -> pd.DataFrame:
    """The UHI file (csv or parquet) as a table."""
    if not path:
        raise ValueError("kies een UHI-bestand (per postcode: pc6 en uhi)")
    p = Path(path)
    if not p.exists():
        raise ValueError(f"UHI-bestand niet gevonden: {path}")
    return lees_parquet(p) if p.suffix.lower() == ".parquet" else pd.read_csv(p)


def read_uhi(path: str) -> dict:
    """postcode6 -> UHI [°C] from a csv or parquet with a postcode and a UHI column."""
    return uhi_table(read_uhi_frame(path))


def bin_uhi(df: pd.DataFrame, step: float, column: str = UHI) -> pd.DataFrame:
    """``df`` with the raw UHI values of ``column`` in classes of ``step`` °C."""
    from .generalize import Bin
    from .risk import QidColumn
    q = QidColumn(column, CATALOGUE["uhi"])
    binned, _ = Bin(column, float(step)).apply(df[[column]].astype(object), [q])
    out = df.copy()
    out[column] = binned[column]
    return out


def add_uhi(df: pd.DataFrame, loc: pd.DataFrame, table: dict, step: float) -> pd.DataFrame:
    """``df`` with a UHI column: the value of each record's postcode, in classes of ``step``."""
    raw = loc["postcode6"].map(table)
    tmp = pd.DataFrame({UHI: raw.astype(object)}, index=df.index)
    out = df.copy()
    out[UHI] = bin_uhi(tmp, step)[UHI]
    return out


_uhi_views = iter(range(1, 1_000_000))


def population_with_uhi(population: Population, frame: pd.DataFrame) -> Population:
    """The population with a UHI column from ``frame`` (a table with a postcode and a UHI
    column), joined on postcode6. Untouched when the population has no postcodes or a UHI
    already."""
    if "uhi" in population.columns or "postcode6" not in population.columns:
        return population
    pc = next(c for c in frame.columns if c.lower() in ("pc6", "postcode6", "postcode"))
    val = next(c for c in frame.columns if c.lower().startswith("uhi"))
    view = f"_uhi_tabel_{next(_uhi_views)}"
    population.con.register(view, frame)
    rel = (f"(SELECT p.*, u.uhi FROM {population.relation} p LEFT JOIN (SELECT "
           f"upper(replace(CAST(\"{pc}\" AS VARCHAR), ' ', '')) AS pc6, "
           f"CAST(\"{val}\" AS DOUBLE) AS uhi FROM {view}) u "
           f"ON u.pc6 = upper(replace(p.postcode6, ' ', '')))")
    return Population(population.con, rel, population.snapshot, population.scope)


# --- a traced weather series --------------------------------------------------------------------
def apply_trace(df: pd.DataFrame, key: str, traced, population: Population, stations=None
                ) -> tuple[pd.DataFrame, float, dict]:
    """Put a traced weather series back into the dataset as ``weer_knmi_station`` and
    ``weerzone_h3`` (per dwelling, through the ``key`` column).

    ``traced`` is what :func:`anonymate.weerspoor.investigate` returned (or its per-home table);
    ``population`` the population, or a function that gives it (only called when needed).
    Returns (new dataframe, tolerance in km, summary) where the tolerance is what an
    approximate match leaves the attacker in doubt, and the summary holds ``added`` ({column:
    qid key}), ``status`` (one line), and, when the investigation gave a conclusion,
    ``verdict``, ``advice`` and ``notes`` (the findings)."""
    from .weerspoor import as_columns
    found = traced
    traced = getattr(found, "per_home", found)
    cols = as_columns(traced)
    cols["woning"] = cols["woning"].astype(str)
    out = df.drop(columns=[c for c in (WEATHER_H3, WEATHER_STATION) if c in df.columns])
    by_home = cols.set_index("woning")
    for col in (WEATHER_STATION, WEATHER_H3):
        values = out[key].astype(str).map(by_home[col])
        out[col] = pd.Series([v if pd.notna(v) else None for v in values], index=out.index,
                             dtype=object)
    added = {c: q for c, q in ((WEATHER_STATION, "knmi_station"), (WEATHER_H3, "h3_cel"))
             if out[c].notna().any()}
    out = out.drop(columns=[c for c in (WEATHER_STATION, WEATHER_H3) if c not in added])
    notes = list(getattr(found, "findings", None) or [])
    if WEATHER_STATION in out.columns:
        try:
            from .weerspoor import check_assignment
            if stations is None:
                stations = traced.attrs.get("stations")
            widened, extra = check_assignment(out, key, traced,
                                              population() if callable(population)
                                              else population, stations)
            merged = [w if w is not None and pd.notna(w) else v
                      for w, v in zip(widened, out[WEATHER_STATION])]
            out[WEATHER_STATION] = pd.Series(
                [x if x is not None and pd.notna(x) else None for x in merged],
                index=out.index, dtype=object)
            notes += extra
        except Exception:  # noqa: BLE001 (the check is extra; the traced station stands)
            pass
    tolerance = float(cols["onzekerheid_km"].max()) \
        if "onzekerheid_km" in cols and cols["onzekerheid_km"].notna().any() else 0.0
    counts = traced["regime"].value_counts().to_dict()
    summary = {"added": added,
               "status": "Teruggeleid: " + ", ".join(f"{k}: {v}" for k, v in counts.items())
               + ". De afgeleide weerlocatie telt mee als verborgen locatie."}
    if hasattr(found, "verdict"):
        summary.update(verdict=found.verdict, advice=found.advice, notes=notes)
    return out, tolerance, summary


# --- the region ---------------------------------------------------------------------------------
def region_scope(heel_nederland: bool, provinces=(), municipalities="") -> dict:
    """The region chosen in step 1 as scope items: {} for the whole country, else
    ``provincie`` and/or ``gemeente`` lists. ``municipalities`` is a list or a text with commas."""
    if heel_nederland:
        return {}
    out = {}
    provinces = list(provinces)
    if provinces:
        out["provincie"] = provinces
    if isinstance(municipalities, str):
        municipalities = municipalities.split(",")
    towns = [t.strip() for t in municipalities if t and t.strip()]
    if towns:
        out["gemeente"] = towns
    return out


def merge_scope(region: dict, free_text: str, population: Population):
    """The scope of the population: the free text (``gemeente=Zwolle; bouwjaar=1900-1989``)
    with the region on top."""
    pairs = [p.strip() for p in (free_text or "").split(";") if p.strip()]
    items = {**_scope_from_args(pairs), **region}
    return parse_scope(items, population)


def region_text(region: dict) -> str:
    """The region in a few words, for the dataset card."""
    if not region:
        return "heel Nederland"
    parts = region.get("provincie", []) + region.get("gemeente", [])
    return ", ".join(parts) if len(parts) <= 2 else f"{len(parts)} gebieden"


# --- the texts of the map and of a dwelling -----------------------------------------------------
def cell_verdict(k_eff: float, k: int) -> str:
    """"ruim genoeg" (twice the norm), "genoeg" or "te weinig": the effective number of
    candidates against the norm k."""
    return "ruim genoeg" if k_eff >= 2 * k else ("genoeg" if k_eff >= k else "te weinig")


def cell_text(stats: dict, level: int, sigma: float, k: int, *, land_share: float | None = None,
              in_dataset: int | None = None) -> dict:
    """What the side card of the map says about a clicked cell, as data.

    ``stats`` is :meth:`anonymate.kaart.MapData.cell_stats`; ``land_share`` the share of the cell
    on land (None: unknown or no map), ``in_dataset`` how many of the dataset's dwellings got
    this cell as weather zone (None: the weather location is not added yet). Values use the
    markup of :func:`html` (``**bold**``, ``!!orange!!``).

    Returns {"title", "rows" [(label, value)], "after_title", "after" [(label, value)],
    "verdict" (plain, or None without noise)}."""
    own, ring = stats["woningen"], stats["met_buren"]
    area = stats["gebied_km2"]
    land = (f", waarvan ~{nr(area * land_share)} km² land"
            if land_share is not None and land_share < 0.95 else "")
    title = f"Cel van niveau {stats['niveau']} · {nr(area)} km²{land}"
    if in_dataset is None:
        mine = "nog onbekend: voeg eerst de weerlocatie toe"
    else:
        mine = f"{in_dataset} woning{'en' if in_dataset != 1 else ''} kreeg deze cel als weerzone"
    rows = [("In deze cel", f"**{nr(own)}** woningen"),
            ("Met de zes buurcellen", f"{nr(ring)} woningen"),
            ("Uit je dataset", mine)]
    verdict = None
    if own and sigma > 0:
        k_eff = stats["k_eff"]
        after = [("Zonder ruis", f"de woning is één van **{nr(own)}** in deze cel"),
                 (f"Met ruis (σ {sigma} km)",
                  f"zo onzeker als één uit **{nr(k_eff)}** even waarschijnlijke woningen: "
                  "woningen dicht bij de cel tellen zwaarder dan verder weg")]
        if "heat_km2" in stats:
            after.append(("Waar de woning dan ligt",
                          f"het !!oranje!! gebied, "
                          f"~{nr(stats['heat_km2'])} km² met {nr(stats['heat_woningen'])} "
                          "woningen (95% van de kans; donkerder is waarschijnlijker)"))
        verdict = cell_verdict(k_eff, k)
        shown = f"**{verdict}**" if verdict == "te weinig" else verdict
        after.append((f"Tegen je norm (k ≥ {k})",
                      f"voor de locatie alleen {shown}. Type, label en de andere "
                      "gepubliceerde kenmerken maken de groep nog kleiner; de toets rekent "
                      "dat per woning uit."))
    elif own:
        after = [("Als deze cel gepubliceerd wordt",
                  f"de woning is één van **{nr(own)}** in deze cel")]
    else:
        after = []
    return {"title": title, "rows": rows,
            "after_title": "Als deze cel bij een woning gepubliceerd wordt", "after": after,
            "verdict": verdict}


def cell_html(card: dict) -> str:
    """The side card of :func:`cell_text` as the HTML the desktop window shows."""
    def table(title, items):
        cells = "".join(f"<tr><td style='padding-right:10px; color:#5B6573'>{a}</td>"
                        f"<td>{html(b)}</td></tr>" for a, b in items)
        return f"<b>{title}</b><table style='margin-top:2px'>{cells}</table>"
    text = table("Wat er ligt", card["rows"])
    if card["after"]:
        text += ("<div style='margin-top:10px'>"
                 + table(card["after_title"], card["after"]) + "</div>")
    return text


def record_card(row, k, norm_k: int, share_in_dataset, status, index: int | None = None
                ) -> tuple[str, str]:
    """Title and text of the card of one dwelling in the outcome. ``row`` holds the dwelling's
    published values (and k, delta, status, redenen, which are not repeated in the text);
    ``share_in_dataset`` is the fraction of look-alikes that sits in the dataset (delta) or
    NaN; ``index`` the 0-based position, for the title."""
    k_int = 0 if k is None or pd.isna(k) else int(k)
    described = ", ".join(str(v).replace("_", " ") for c, v in row.items()
                          if c not in ("k", "delta", "status", "redenen") and pd.notna(v))
    title = f"Woning {index + 1} · {STATUS_TEXT.get(status, status)}" if index is not None \
        else STATUS_TEXT.get(status, status)
    if status == Status.NO_MATCH:
        body = (f"{described}: geen enkele woning in de populatie past hierop. Dat is geen "
                "veiligheid: een aanvaller laat het afwijkende kenmerk weg en zoekt verder.")
    else:
        share = "" if share_in_dataset is None or pd.isna(share_in_dataset) else (
            f" Van die woningen zit {nl(100 * float(share_in_dataset), 0)}% in de dataset.")
        verdict = ("Dat haalt de norm." if status == Status.OK else
                   f"De norm vraagt er {norm_k}: deze woning komt niet in publiceerbaar.csv.")
        count = f"{k_int:,}".replace(",", ".")
        body = f"{described}. In de populatie: {count} zulke woningen.{share} {verdict}"
    return title, body


# --- the Toelichting ----------------------------------------------------------------------------
def representativeness_lines(df, keep, cols) -> list[str]:
    """What leaving out the risky records does to the published columns (notitie 8): ``keep``
    marks the records that stay, ``cols`` the published columns."""
    from .representativiteit import shift
    try:
        table = shift(df, keep, cols, draws=100)
    except Exception:  # noqa: BLE001 (an extra; the assessment itself stands)
        return []
    moved = table[(table["oordeel"] != "verwaarloosbaar") & (table["toeval"].fillna(1) < 0.05)]
    if moved.empty:
        return ["Representativiteit: het weglaten verschuift geen enkele kolom meer dan bij "
                "toeval (details in rapport.md)."]
    parts = [f"{r.kolom} ({r.maat} {r.waarde:+.2f}{'; ' + r.toelichting if r.toelichting else ''})"
             for r in moved.itertuples()]
    return ["Representativiteit: het weglaten verschuift meer dan bij toeval: "
            + "; ".join(parts) + ". Een analyse op het gepubliceerde deel kan daardoor "
            "afwijken; grover publiceren houdt die woningen erin (details in rapport.md)."]


# --- errors -------------------------------------------------------------------------------------
def readable_error(exc) -> str:
    """A message for people, not programmers: expected problems (ValueError and friends) as
    their own text, anything else as a plain 'something went wrong' with the detail kept.
    ``exc`` is an exception or its text as "TypeName: message"."""
    message = f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc)
    m = re.match(r"^(\w+(?:Error|Exception)):\s*(.*)$", message, re.S)
    if not m:
        return message
    kind, text = m.groups()
    if kind in ("ValueError", "FileNotFoundError"):
        return text.split(" / ")[0]
    return ("Er ging iets onverwachts mis. Probeer het opnieuw, of meld het met deze tekst: "
            f"{kind}: {text}")
