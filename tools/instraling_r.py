"""Leidt de instralingsverhoudingen R_o van signature.py af (verticaal vlak per windrichting).

Haalt de KNMI-uurgegevens van globale straling Q (J/cm2 per uur) van De Bilt (260) voor het
stookseizoen oktober 2025 - april 2026 op (hetzelfde seizoen als tools/infiltratie_k.py),
schrijft ze als W/m2 naar docs/data/knmi_260_straling_2025-26.csv en drukt de acht R_o af:
som(instraling op een verticaal vlak) / som(GHI), zie anonymate.instraling. Netwerk staat hier,
niet in de kern.

    .venv/Scripts/python tools/instraling_r.py
"""
import io
import urllib.request
from pathlib import Path

import pandas as pd

from anonymate.instraling import RICHTINGEN, r_verticaal_per_richting

URL = "https://www.daggegevens.knmi.nl/klimatologie/uurgegevens"
OUT = Path(__file__).resolve().parents[1] / "docs" / "data" / "knmi_260_straling_2025-26.csv"


def fetch() -> pd.DataFrame:
    body = b"start=2025100101&end=2026043024&vars=Q&stns=260&fmt=csv"
    text = urllib.request.urlopen(urllib.request.Request(URL, data=body), timeout=120).read()
    lines = [ln for ln in text.decode("utf-8").splitlines() if ln and not ln.startswith("#")]
    df = pd.read_csv(io.StringIO("\n".join(lines)), names=["stn", "datum", "uur", "Q"],
                     skipinitialspace=True)
    time = (pd.to_datetime(df["datum"].astype(str), format="%Y%m%d")
            + pd.to_timedelta(df["uur"] - 1, unit="h"))       # start of the hour ending at HH UT
    # Q is J/cm2 in the hour: x 10^4 cm2/m2 / 3600 s = W/m2 (hour mean)
    return pd.DataFrame({"tijd_utc": time, "GHI__W_m_2": (df["Q"] * 10000 / 3600).round(1)})


if __name__ == "__main__":
    data = fetch().dropna()
    data = data[data["tijd_utc"] < "2026-05-01"]      # 'end=...24' also returns the next day
    data.to_csv(OUT, index=False)
    print(f"{len(data)} uren naar {OUT}")
    r = r_verticaal_per_richting(data["tijd_utc"], data["GHI__W_m_2"])
    for name, val in zip(RICHTINGEN, r):
        print(name, round(float(val), 4))
    print("gemiddelde N/O/Z/W", round(float(r[[0, 2, 4, 6]].mean()), 4))
