"""Rijksdriehoeksmeting (EPSG:28992) to WGS84, vectorised, without pyproj.

Polynomial approximation by Schreutelkamp & Strang van Hees (2001); accurate to about a metre
across the Netherlands, which is far finer than anything this tool needs (H3 cells, nearest
weather station).
"""
from __future__ import annotations

import numpy as np

_X0, _Y0 = 155_000.0, 463_000.0
_PHI0, _LAM0 = 52.15517440, 5.38720621

_K = {(0, 1): 3235.65389, (2, 0): -32.58297, (0, 2): -0.24750, (2, 1): -0.84978,
      (0, 3): -0.06550, (2, 2): -0.01709, (1, 0): -0.00738, (4, 0): 0.00530,
      (2, 3): -0.00039, (4, 1): 0.00033, (1, 1): -0.00012}
_L = {(1, 0): 5260.52916, (1, 1): 105.94684, (1, 2): 2.45656, (3, 0): -0.81885,
      (1, 3): 0.05594, (3, 1): -0.05607, (0, 1): 0.01199, (3, 2): -0.00256,
      (1, 4): 0.00128, (0, 2): 0.00022, (2, 0): -0.00022, (5, 0): 0.00026}


def rd_to_wgs84(x, y):
    """Return ``(lat, lon)`` arrays in degrees for RD ``x, y`` in metres."""
    dx = (np.asarray(x, dtype=float) - _X0) * 1e-5
    dy = (np.asarray(y, dtype=float) - _Y0) * 1e-5
    lat = _PHI0 + sum(k * dx**p * dy**q for (p, q), k in _K.items()) / 3600
    lon = _LAM0 + sum(k * dx**p * dy**q for (p, q), k in _L.items()) / 3600
    return lat, lon


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))
