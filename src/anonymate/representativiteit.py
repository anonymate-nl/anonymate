"""Representativeness: what leaving out records does (:func:`shift`), and how the dataset compares
with its target population (:func:`vergelijk`). Kladbloknotitie 7.

:func:`vergelijk` is meant for publication *instead of* the features per record: per feature the
measure, its chance share, the population's class shares and the direction of each difference,
with every parameter needed to recompute it. See its docstring for what it does and does not leak.

The assessment does not drop records at random: it takes away the tails (large, old, detached
dwellings, sparsely populated areas), which are often also the ones with the largest heat demand.
Per published column this module compares the whole dataset with the publishable part:

* numbers: the standardised mean difference (SMD), the shift of the mean in standard deviations
  of the whole dataset; rule of thumb from epidemiology: |SMD| < 0.1 is negligible;
* categories (and generalised values such as "1970-1979"): the total variation distance (TVD),
  half the sum of the absolute differences in share, missing values counted as a category.

With a few hundred records a handful of omissions can shift a distribution by chance alone. So
each shift is also compared with leaving out the same number of records at random: ``toeval`` is
the share of random omissions that shift the column at least as much. A small share means the
shift comes from *which* records were left out, not from how many.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .link import _missing
from .population import Population, _quote

SMD_SMALL, SMD_NOTABLE = 0.1, 0.2
TVD_SMALL, TVD_NOTABLE = 0.05, 0.10
DRAWS = 200


def _numeric(values: pd.Series) -> pd.Series | None:
    present = values.dropna()
    if present.empty:
        return None
    num = pd.to_numeric(present, errors="coerce")
    return pd.to_numeric(values, errors="coerce") if num.notna().mean() >= 0.9 else None


def _smd(x: np.ndarray, keep: np.ndarray, sd: float) -> float:
    kept = x[keep & ~np.isnan(x)]
    if not len(kept) or not sd:
        return 0.0
    return float((kept.mean() - np.nanmean(x)) / sd)


def _tvd(codes: np.ndarray, keep: np.ndarray, n_codes: int) -> float:
    whole = np.bincount(codes, minlength=n_codes) / len(codes)
    part = np.bincount(codes[keep], minlength=n_codes) / max(int(keep.sum()), 1)
    return float(0.5 * np.abs(whole - part).sum())


def _verdict(size: float, small: float, notable: float) -> str:
    return ("verwaarloosbaar" if size < small else "klein" if size < notable else "merkbaar")


def shift(df: pd.DataFrame, keep: pd.Series, columns=None, *, draws: int = DRAWS,
          seed: int = 0) -> pd.DataFrame:
    """Per column: measure, size, verdict and the chance share (see module docstring).

    ``keep`` marks the records that are published. Columns default to all of ``df``.
    """
    keep = np.asarray(keep, dtype=bool)
    n, dropped = len(df), int((~keep).sum())
    rows = []
    rng = np.random.default_rng(seed)
    # the same random omissions for every column, so columns stay comparable
    random_keeps = []
    if 0 < dropped < n:
        for _ in range(draws):
            k = np.ones(n, dtype=bool)
            k[rng.choice(n, dropped, replace=False)] = False
            random_keeps.append(k)
    for col in (columns if columns is not None else df.columns):
        values = df[col]
        num = _numeric(values)
        if num is not None:
            x = num.to_numpy(dtype=float)
            sd = float(np.nanstd(x))
            size = _smd(x, keep, sd)
            chance = [abs(_smd(x, k, sd)) for k in random_keeps]
            measure, verdict = "SMD", _verdict(abs(size), SMD_SMALL, SMD_NOTABLE)
            detail = (f"gemiddelde {np.nanmean(x):.4g} → {np.nanmean(x[keep]):.4g}"
                      if keep.any() else "")
        else:
            codes, uniques = pd.factorize(values.astype(object).where(values.notna(), "(leeg)"))
            size = _tvd(codes, keep, len(uniques))
            chance = [_tvd(codes, k, len(uniques)) for k in random_keeps]
            measure, verdict = "TVD", _verdict(size, TVD_SMALL, TVD_NOTABLE)
            detail = _largest_change(values, keep)
        rows.append({
            "kolom": col, "maat": measure, "waarde": round(size, 3), "oordeel": verdict,
            "toeval": round(float(np.mean([c >= abs(size) - 1e-12 for c in chance])), 3)
            if chance else None,
            "toelichting": detail,
        })
    out = pd.DataFrame(rows, columns=["kolom", "maat", "waarde", "oordeel", "toeval",
                                      "toelichting"])
    out.attrs.update({"records": n, "weggelaten": dropped})
    return out


def _largest_change(values: pd.Series, keep: np.ndarray) -> str:
    """The category whose share changes most, e.g. 'vrijstaand 14% → 9%'."""
    v = values.astype(object).where(values.notna(), "(leeg)")
    whole = v.value_counts(normalize=True)
    part = v[keep].value_counts(normalize=True).reindex(whole.index, fill_value=0.0)
    if whole.empty:
        return ""
    cat = (part - whole).abs().idxmax()
    return f"{cat}: {100 * whole[cat]:.0f}% → {100 * part[cat]:.0f}%"


def markdown(table: pd.DataFrame) -> str:
    """A section for rapport.md."""
    n, dropped = table.attrs.get("records", 0), table.attrs.get("weggelaten", 0)
    lines = ["## Representativiteit: wat doet het weglaten? / representativeness", ""]
    if not dropped:
        return "\n".join(lines + ["Er worden geen records weggelaten.", ""])
    lines += [
        f"{dropped} van {n} records worden niet gepubliceerd. Per kolom de verschuiving tussen de "
        "hele dataset en het gepubliceerde deel: SMD voor getallen (verschuiving van het "
        f"gemiddelde in standaardafwijkingen; |SMD| < {SMD_SMALL:g} is verwaarloosbaar), TVD voor "
        f"categorieën (verschil in verdeling, 0 tot 1; < {TVD_SMALL:g} is verwaarloosbaar). "
        "*Toeval* is het deel van willekeurige weglatingen van evenveel records dat minstens "
        "zoveel verschuift: klein betekent dat de verschuiving komt door *welke* records "
        "wegvallen.",
        "",
        "| kolom | maat | waarde | oordeel | toeval | grootste verandering |",
        "|---|---|---|---|---|---|",
    ]
    order = {"merkbaar": 0, "klein": 1, "verwaarloosbaar": 2}
    for r in table.sort_values("oordeel", key=lambda s: s.map(order)).itertuples():
        chance = "–" if r.toeval is None else f"{100 * r.toeval:.0f}%"
        lines.append(f"| {r.kolom} | {r.maat} | {r.waarde:+.2f} | {r.oordeel} | {chance} | "
                     f"{r.toelichting} |" if r.maat == "SMD" else
                     f"| {r.kolom} | {r.maat} | {r.waarde:.2f} | {r.oordeel} | {chance} | "
                     f"{r.toelichting} |")
    notable = table[(table["oordeel"] != "verwaarloosbaar")
                    & (table["toeval"].fillna(1) < 0.05)]
    lines.append("")
    if len(notable):
        lines += [f"Let op: {', '.join(notable['kolom'])} verschuift meer dan bij toeval. Een "
                  "analyse op het gepubliceerde deel kan daardoor afwijken; overweeg grover "
                  "publiceren in plaats van weglaten (een staartklasse samenvoegen houdt de "
                  "woningen in de dataset), of vermeld de verschuiving bij de publicatie.", ""]
    return "\n".join(lines)


# ------------------------------------------------------------------------------------------------
# the dataset against its target population
# ------------------------------------------------------------------------------------------------

LEEG = "(leeg)"
QUANTILES = 1000  # population quantiles for the Wasserstein distance and the random draws
CHANCE_DRAWS = 1000
_TEXT_SUFFIXES = ("__cat", "__str", "__bool")
_NUMERIC_TYPES = ("TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UTINYINT", "USMALLINT",
                  "UINTEGER", "UBIGINT", "FLOAT", "REAL", "DOUBLE", "DECIMAL")


@dataclass(frozen=True)
class Kenmerk:
    """A feature to compare: ``kolom`` in the population, ``bron`` in the dataset (default: the
    same name). ``grenzen`` gives classes for a number: below the first edge, [a, b) between two
    edges, and from the last edge up."""

    kolom: str
    bron: str | None = None
    grenzen: tuple[float, ...] = ()


@dataclass
class Vergelijking:
    """Outcome of :func:`vergelijk`: everything in it is meant to be publishable."""

    kenmerken: pd.DataFrame
    klassen: pd.DataFrame
    parameters: dict
    waarschuwingen: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        def rows(t: pd.DataFrame) -> list[dict]:
            return [{k: _plain(v) for k, v in r.items()} for r in t.to_dict("records")]
        return {"parameters": self.parameters, "kenmerken": rows(self.kenmerken),
                "klassen": rows(self.klassen), "waarschuwingen": list(self.waarschuwingen)}

    def markdown(self) -> str:
        """A section for rapport.md."""
        p = self.parameters
        lines = [
            "## Representativiteit: dataset tegenover de doelpopulatie / representativeness", "",
            f"{p['vergeleken']} records vergeleken met {p['populatie_woningen']:,} woningen in de "
            f"doelpopulatie ({p['afbakening'] or 'zonder afbakening'}). SMD voor getallen "
            f"(verschil van het gemiddelde in standaardafwijkingen van de populatie; < "
            f"{SMD_SMALL:g} is verwaarloosbaar), met de Wasserstein-afstand in dezelfde eenheid; "
            f"TVD voor categorieën (0 tot 1; < {TVD_SMALL:g} is verwaarloosbaar). *Toeval*: het "
            f"deel van {p['trekkingen']} aselecte steekproeven van evenveel woningen uit de "
            "populatie dat minstens zoveel afwijkt. Klein betekent: de dataset wijkt meer af dan "
            "een aselecte steekproef zou doen.", "",
            "| kenmerk | n | maat | waarde | Wasserstein | oordeel | toeval | toelichting |",
            "|---|---:|---|---:|---:|---|---:|---|",
        ]
        for r in self.kenmerken.itertuples():
            w = "–" if _plain(r.wasserstein) is None else f"{r.wasserstein:.2f}"
            val = ("–" if _plain(r.waarde) is None else
                   f"{r.waarde:+.2f}" if r.maat == "SMD" else f"{r.waarde:.2f}")
            chance = "–" if _plain(r.toeval) is None else f"{100 * r.toeval:.0f}%"
            lines.append(f"| {r.kenmerk} | {r.n} | {r.maat} | {val} | {w} | {r.oordeel} | "
                         f"{chance} | {r.toelichting} |")
        if len(self.klassen):
            lines += ["", "Per klasse het aandeel in de populatie en de richting van de dataset; "
                      f"het aandeel in de dataset alleen als de klasse minstens {p['k']} records "
                      "heeft.", "",
                      "| kenmerk | klasse | populatie | dataset | richting |",
                      "|---|---|---:|---:|:---:|"]
            for r in self.klassen.itertuples():
                ds = "< k" if _plain(r.dataset) is None else f"{100 * r.dataset:.1f}%"
                lines.append(f"| {r.kenmerk} | {r.klasse} | {100 * r.populatie:.1f}% | {ds} | "
                             f"{r.richting} |")
        if self.waarschuwingen:
            lines += [""] + [f"Let op: {w}" for w in self.waarschuwingen]
        features = ", ".join(
            f["kolom"] + (f" (grenzen {', '.join(f'{g:g}' for g in f['grenzen'])})"
                          if f["grenzen"] else "") for f in p["kenmerken"])
        lines += ["", "Parameters, om na te rekenen: "
                  + "; ".join(f"{key} {_describe(v)}" for key, v in p.items()
                              if key != "kenmerken")
                  + f"; kenmerken {features}.", ""]
        return "\n".join(lines)


def _plain(v):
    """A JSON-ready value: NaN and NA become None, numpy scalars Python ones."""
    if v is None or (not isinstance(v, (list, tuple, dict, str)) and bool(pd.isna(v))):
        return None
    if isinstance(v, np.generic):
        return v.item()
    return v


def _describe(v) -> str:
    return f"{v:,}" if isinstance(v, int) and not isinstance(v, bool) else str(v)


def _text(v) -> str:
    """A dataset value as DuckDB's ``CAST(... AS VARCHAR)`` writes it."""
    if _missing(v):
        return LEEG
    if isinstance(v, (bool, np.bool_)):
        return "true" if v else "false"
    if isinstance(v, (float, np.floating)) and float(v).is_integer():
        return str(int(v))
    return str(v)


def _is_numeric(population: Population, column: str) -> bool:
    if column.endswith(_TEXT_SUFFIXES):
        return False
    kind = population.con.execute(
        f"DESCRIBE SELECT {_quote(column)} FROM {population.relation}").fetchone()[1]
    return str(kind).upper().startswith(_NUMERIC_TYPES)


def _class_labels(edges: tuple[float, ...]) -> list[tuple[str, float | None, float | None]]:
    out = [(f"< {edges[0]:g}", None, edges[0])]
    out += [(f"{a:g} tot {b:g}", a, b) for a, b in zip(edges, edges[1:])]
    return out + [(f"≥ {edges[-1]:g}", edges[-1], None)]


def _direction(share: float, population_share: float) -> str:
    if share > population_share + 1e-9:
        return "+"
    return "−" if share < population_share - 1e-9 else "="


def _chance(observed: float, draws: np.ndarray) -> float:
    return round(float(np.mean(draws >= observed - 1e-12)), 3)


def vergelijk(df: pd.DataFrame, population: Population, kenmerken, *, k: int = 11,
              draws: int = CHANCE_DRAWS, seed: int = 0) -> Vergelijking:
    """Compare the dataset with its target population, feature by feature.

    ``population`` is the target population with its scope (the same afbakening as the privacy
    assessment); ``kenmerken`` are :class:`Kenmerk` or population column names. Use register
    values on both sides where possible (link the dataset first), so that a difference is not a
    difference in definition.

    Per feature: SMD and the Wasserstein distance (both in population standard deviations) for a
    number, TVD for a category, and ``toeval``: the share of ``draws`` random samples of the same
    size from the population that differ at least as much. With ``grenzen`` a number also gets a
    class table. A missing number is left out of that number (and counted as class ``(leeg)``);
    a missing category is a category of its own.

    What the outcome leaks: the dataset share of a class is only given when the class holds at
    least ``k`` records; a smaller class gets only the direction. A feature where every record
    falls in one class is known for every record; :attr:`Vergelijking.waarschuwingen` says so.
    That is fine for a public inclusion criterion (it then belongs in the scope); otherwise
    assess the feature as a QID. The class shares are also a prior for an attacker; publish them
    only for features the assessment can bear.
    """
    rng = np.random.default_rng(seed)
    specs = [m if isinstance(m, Kenmerk) else Kenmerk(m) for m in kenmerken]
    params: list = []
    where = population.where(params)
    ctx = (population.relation, population.con, where, params, rng, draws, k)
    rows, classes, warnings = [], [], []
    for spec in specs:
        population.require(spec.kolom)
        values = df[spec.bron or spec.kolom]
        compare = (_compare_number if spec.grenzen or _is_numeric(population, spec.kolom)
                   else _compare_category)
        row, cls = compare(values, spec, *ctx)
        rows.append(row)
        classes += cls
        whole = [c for c in cls if row["n"] and c["_count"] == row["n"]]
        if whole and whole[0]["populatie"] < 1 - 1e-9:
            warnings.append(f"alle records vallen bij {spec.kolom} in klasse {whole[0]['klasse']}: "
                            "dat kenmerk is daarmee per record bekend. Alleen goed als het een "
                            "openbaar inclusiecriterium is (dan hoort het in de afbakening); "
                            "anders meetoetsen als QID, of de klassen niet publiceren.")
    if len(df) < k:
        warnings.append(f"de dataset heeft minder dan {k} records: geen aandelen per klasse, en "
                        "ook de maten zeggen dan weinig.")
    from . import __version__
    parameters = {
        "anonymate": __version__, "populatie": population.snapshot.describe(),
        "afbakening": population.scope.description, "populatie_woningen": population.size(),
        "vergeleken": len(df), "k": k, "trekkingen": draws, "seed": seed,
        "kwantielen": QUANTILES,
        "kenmerken": [{"kolom": s.kolom, "grenzen": [float(g) for g in s.grenzen]}
                      for s in specs],
    }
    table = pd.DataFrame(rows, columns=["kenmerk", "n", "maat", "waarde", "wasserstein",
                                        "oordeel", "toeval", "toelichting"])
    klassen = pd.DataFrame([{c: v for c, v in r.items() if not c.startswith("_")}
                            for r in classes],
                           columns=["kenmerk", "klasse", "populatie", "dataset", "richting"])
    return Vergelijking(table, klassen, parameters, warnings)


def _class_rows(column: str, labels: list[str], pop_counts: np.ndarray, ds_counts: np.ndarray,
                k: int) -> list[dict]:
    n, total = int(ds_counts.sum()), max(float(pop_counts.sum()), 1.0)
    out = []
    for label, pc, dc in zip(labels, pop_counts, ds_counts):
        if not pc and not dc:
            continue
        share = dc / n if n else 0.0
        out.append({"kenmerk": column, "klasse": label, "populatie": round(pc / total, 4),
                    "dataset": round(share, 4) if dc >= k else None,
                    "richting": _direction(share, pc / total), "_count": int(dc)})
    return out


def _compare_category(values, spec, rel, con, where, params, rng, draws, k):
    q = _quote(spec.kolom)
    pop = dict(con.execute(f"SELECT coalesce(CAST({q} AS VARCHAR), '{LEEG}'), count(*) "
                           f"FROM {rel} WHERE {where} GROUP BY 1", params).fetchall())
    ds = values.map(_text).value_counts()
    labels = sorted(set(pop) | set(ds.index), key=lambda c: (c == LEEG, str(c)))
    pop_counts = np.array([pop.get(c, 0) for c in labels], dtype=float)
    ds_counts = np.array([int(ds.get(c, 0)) for c in labels])
    n = int(ds_counts.sum())
    p = pop_counts / max(pop_counts.sum(), 1.0)
    size = float(0.5 * np.abs(ds_counts / max(n, 1) - p).sum())
    chance = None
    if n:
        sample = rng.multinomial(n, p, size=draws) / n
        chance = _chance(size, 0.5 * np.abs(sample - p).sum(axis=1))
    cls = _class_rows(spec.kolom, labels, pop_counts, ds_counts, k)
    large = [c for c in cls if c["dataset"] is not None]
    detail = ""
    if large:
        c = max(large, key=lambda c: abs(c["dataset"] - c["populatie"]))
        detail = (f"{c['klasse']}: populatie {100 * c['populatie']:.0f}%, "
                  f"dataset {100 * c['dataset']:.0f}%")
    row = {"kenmerk": spec.kolom, "n": n, "maat": "TVD", "waarde": round(size, 3),
           "wasserstein": None, "oordeel": _verdict(size, TVD_SMALL, TVD_NOTABLE),
           "toeval": chance, "toelichting": detail}
    return row, cls


def _compare_number(values, spec, rel, con, where, params, rng, draws, k):
    q = _quote(spec.kolom)
    grid = (np.arange(QUANTILES) + 0.5) / QUANTILES
    labels = _class_labels(tuple(sorted(spec.grenzen))) if spec.grenzen else []
    filters = []
    for _, lo, hi in labels:
        cond = " AND ".join(([f"{q} >= {float(lo)!r}"] if lo is not None else [])
                            + ([f"{q} < {float(hi)!r}"] if hi is not None else []))
        filters.append(f", count(*) FILTER (WHERE {cond})")
    res = con.execute(
        f"SELECT avg({q}), stddev_pop({q}), "
        f"quantile_cont({q}, [{', '.join(f'{g:.6f}' for g in grid)}]), "
        f"count(*) FILTER (WHERE {q} IS NULL){''.join(filters)} FROM {rel} WHERE {where}",
        params).fetchone()
    mu, sd = res[0], float(res[1] or 0.0)
    qpop = np.asarray(res[2] or [], dtype=float)
    x = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    present = x[~np.isnan(x)]
    n = len(present)
    smd = wass = chance = None
    if n and mu is not None and sd:
        smd = float((present.mean() - mu) / sd)
        wass = float(np.mean(np.abs(np.quantile(present, grid) - qpop)) / sd)
        found = []
        for start in range(0, draws, 100):  # in blocks: draws x n numbers at once can be large
            u = rng.random((min(100, draws - start), n))
            found.append(np.abs((np.interp(u, grid, qpop).mean(axis=1) - mu) / sd))
        chance = _chance(abs(smd), np.concatenate(found))
    cls = []
    if labels:
        inside = [(np.ones(len(x), bool) if lo is None else x >= lo)
                  & (np.ones(len(x), bool) if hi is None else x < hi) for _, lo, hi in labels]
        ds_counts = np.array([int(m.sum()) for m in inside] + [int(np.isnan(x).sum())])
        pop_counts = np.array(list(res[4:]) + [res[3]], dtype=float)
        cls = _class_rows(spec.kolom, [lab for lab, _, _ in labels] + [LEEG], pop_counts,
                          ds_counts, k)
    detail = (f"gemiddelde populatie {mu:.4g}, dataset {present.mean():.4g}"
              if smd is not None and n >= k else "")
    row = {"kenmerk": spec.kolom, "n": n, "maat": "SMD",
           "waarde": None if smd is None else round(smd, 3),
           "wasserstein": None if wass is None else round(wass, 3),
           "oordeel": "" if smd is None else _verdict(abs(smd), SMD_SMALL, SMD_NOTABLE),
           "toeval": chance, "toelichting": detail}
    return row, cls
