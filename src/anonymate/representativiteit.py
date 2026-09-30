"""How much does leaving out records shift the dataset? (kladbloknotitie 7)

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

import numpy as np
import pandas as pd

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
