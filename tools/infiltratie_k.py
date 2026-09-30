"""Leidt de linearisatieconstanten LBL_K__0 van signature.py af.

Haalt de KNMI-uurgegevens (FH windsnelheid 10 m, T temperatuur) van De Bilt (260) voor het
stookseizoen oktober 2025 - april 2026 op, schrijft ze naar docs/data/knmi_260_uur_2025-26.csv en
drukt k per bouwlagenklasse af:  A_inf = ELA * k,  k = 10 * som(sqrt(Cs dT + Cw v^2) * dT) /
som(v * dT), T_binnen 20 graden, uren met dT > 0. Netwerk staat hier, niet in de kern.

    .venv/Scripts/python tools/infiltratie_k.py
"""
import io
import urllib.request
from pathlib import Path

import pandas as pd

from anonymate.signature import lbl_linearisation

URL = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"
OUT = Path(__file__).resolve().parents[1] / "docs" / "data" / "knmi_260_uur_2025-26.csv"


def fetch() -> pd.DataFrame:
    body = b"start=2025100101&end=2026043024&vars=FH:T&stns=260&fmt=csv"
    text = urllib.request.urlopen(urllib.request.Request(URL, data=body), timeout=120).read()
    lines = [ln for ln in text.decode("utf-8").splitlines() if ln and not ln.startswith("#")]
    df = pd.read_csv(io.StringIO("\n".join(lines)), names=["stn", "datum", "uur", "FH", "T"],
                     skipinitialspace=True)
    time = (pd.to_datetime(df["datum"].astype(str), format="%Y%m%d")
            + pd.to_timedelta(df["uur"] - 1, unit="h"))       # start of the hour ending at HH UT
    return pd.DataFrame({"tijd_utc": time, "FH__m_s": df["FH"] / 10.0, "T__C": df["T"] / 10.0})


if __name__ == "__main__":
    data = fetch().dropna()
    data = data[data["tijd_utc"] < "2026-05-01"]      # 'end=...24' also returns the next day
    data.to_csv(OUT, index=False)
    print(f"{len(data)} uren naar {OUT}")
    for n in (1, 2, 3):
        print(n, round(lbl_linearisation(data["T__C"], data["FH__m_s"], n), 6))
