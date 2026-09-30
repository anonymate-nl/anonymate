"""Instraling op een verticaal vlak per windrichting, uit uurwaarden van de globale straling.

Gebruikt voor de verhoudingen ``R_o`` in :mod:`anonymate.signature`: energie op een verticaal vlak
gericht op richting ``o`` gedeeld door de energie op een horizontaal vlak (GHI). Alles zelf
geschreven, in numpy; geen netwerk en geen extra afhankelijkheid.

Methode, per uur:

1. zonspositie volgens het NOAA-algoritme (Spencer-reeksen voor declinatie en tijdvergelijking),
   op het midden van het uur;
2. GHI splitsen in diffuus (DHI) en direct (DNI) met de correlatie van Erbs et al. (1982), op de
   heldere-hemelindex k_t = GHI / (I_0 cos z);
3. transpositie naar het verticale vlak met Hay & Davies (1980): direct + circumsolaire
   component (anisotropie-index AI = DNI / I_0n) + isotroop diffuus (1 + cos β) / 2, en
   grondreflectie met albedo 0,2 op GHI (1 - cos β) / 2.

Bronnen: Erbs, Klein & Duffie (1982), Solar Energy 28(4); Hay & Davies (1980), Proc. First
Canadian Solar Radiation Data Workshop; NOAA Global Monitoring Laboratory, Solar Calculator.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RICHTINGEN = ("N", "NO", "O", "ZO", "Z", "ZW", "W", "NW")
AZIMUTH__deg = np.arange(8) * 45.0          # kompas, met de klok mee vanaf noord
DE_BILT_LAT__deg = 52.10
DE_BILT_LON__deg = 5.18
SOLAR_CONSTANT__W_m_2 = 1361.0
ALBEDO__0 = 0.2
SEASON_MONTHS = (10, 11, 12, 1, 2, 3, 4)    # stookseizoen oktober - april
_COS_Z_SUN__0 = 0.0175                      # zon lager dan ~1 graad boven de horizon: alles diffuus
_COS_Z_MIN__0 = 0.065                       # ondergrens van cos z in k_t en DNI (hoogte 3,7 graden),
#                                             zoals in de gangbare implementaties van Erbs


def zonspositie(tijd_utc, lat__deg: float = DE_BILT_LAT__deg, lon__deg: float = DE_BILT_LON__deg):
    """(cos zenit, azimut [graden, kompas], extraterrestrische normale straling [W/m2]).

    ``tijd_utc``: het *midden* van elk uur, in UT.
    """
    t = pd.DatetimeIndex(tijd_utc)
    doy = t.dayofyear.to_numpy(dtype=float)
    hour = t.hour.to_numpy() + t.minute.to_numpy() / 60.0 + t.second.to_numpy() / 3600.0
    g = 2 * np.pi / 365.0 * (doy - 1 + (hour - 12) / 24)
    eqtime = 229.18 * (0.000075 + 0.001868 * np.cos(g) - 0.032077 * np.sin(g)
                       - 0.014615 * np.cos(2 * g) - 0.040849 * np.sin(2 * g))         # min
    decl = (0.006918 - 0.399912 * np.cos(g) + 0.070257 * np.sin(g) - 0.006758 * np.cos(2 * g)
            + 0.000907 * np.sin(2 * g) - 0.002697 * np.cos(3 * g) + 0.00148 * np.sin(3 * g))
    e0 = (1.00011 + 0.034221 * np.cos(g) + 0.00128 * np.sin(g) + 0.000719 * np.cos(2 * g)
          + 0.000077 * np.sin(2 * g))
    ha = np.radians((hour * 60 + eqtime + 4 * lon__deg) / 4 - 180)
    lat = np.radians(lat__deg)
    cos_z = np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(ha)
    az = np.arctan2(np.sin(ha), np.cos(ha) * np.sin(lat) - np.tan(decl) * np.cos(lat)) + np.pi
    return cos_z, np.degrees(az) % 360.0, SOLAR_CONSTANT__W_m_2 * e0


def erbs_diffuse_fraction(kt):
    """Diffuse fraction DHI / GHI as a function of the clearness index (Erbs et al., 1982)."""
    kt = np.clip(np.asarray(kt, dtype=float), 0.0, 1.0)
    mid = 0.9511 - 0.1604 * kt + 4.388 * kt**2 - 16.638 * kt**3 + 12.336 * kt**4
    return np.where(kt <= 0.22, 1 - 0.09 * kt, np.where(kt <= 0.80, mid, 0.165))


def verticaal_per_richting(tijd_start_utc, ghi__W_m_2, azimuth__deg=AZIMUTH__deg,
                           albedo__0: float = ALBEDO__0, lat__deg: float = DE_BILT_LAT__deg,
                           lon__deg: float = DE_BILT_LON__deg) -> np.ndarray:
    """Instraling op een verticaal vlak [W/m2], uur voor uur: vorm ``(uren, richtingen)``.

    ``tijd_start_utc``: begin van elk uur (UT); ``ghi__W_m_2``: het uurgemiddelde van de globale
    horizontale straling.
    """
    start = pd.DatetimeIndex(tijd_start_utc)
    ghi = np.maximum(np.asarray(ghi__W_m_2, dtype=float), 0.0)
    cos_z, az_sun, i0n = zonspositie(start + pd.Timedelta(minutes=30), lat__deg, lon__deg)
    sun_up = cos_z > _COS_Z_SUN__0
    cz = np.maximum(cos_z, _COS_Z_MIN__0)
    kt = np.where(sun_up, np.minimum(ghi / (i0n * cz), 1.0), 0.0)
    dhi = np.where(sun_up, erbs_diffuse_fraction(kt) * ghi, ghi)
    dni = np.where(sun_up, (ghi - dhi) / cz, 0.0)
    ai = np.clip(dni / i0n, 0.0, 1.0)                      # Hay-Davies anisotropy index
    sin_z = np.sqrt(np.clip(1 - cos_z**2, 0.0, 1.0))
    out = np.empty((len(ghi), len(azimuth__deg)))
    for j, a in enumerate(azimuth__deg):
        cos_theta = np.where(sun_up, np.maximum(sin_z * np.cos(np.radians(az_sun - a)), 0.0), 0.0)
        rb = cos_theta / cz
        direct = dni * cos_theta
        diffuse = dhi * (ai * rb + (1 - ai) * 0.5)         # (1 + cos 90) / 2
        out[:, j] = direct + diffuse + ghi * albedo__0 * 0.5   # (1 - cos 90) / 2
    return out


def r_verticaal_per_richting(tijd_start_utc, ghi__W_m_2, **kw) -> np.ndarray:
    """Acht verhoudingen R_o [W/W]: som(verticaal vlak) / som(GHI) over de stookseizoen-uren
    (oktober - april), naar energie gewogen; in de volgorde van :data:`RICHTINGEN`."""
    start = pd.DatetimeIndex(tijd_start_utc)
    season = np.isin(start.month, SEASON_MONTHS)
    ghi = np.asarray(ghi__W_m_2, dtype=float)
    poa = verticaal_per_richting(start, ghi, **kw)
    return poa[season].sum(axis=0) / np.maximum(ghi[season], 0.0).sum()
