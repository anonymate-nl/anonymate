"""What every test shares: none of them sees the developer's own settings.

Without this, ``Store.open`` in a test read ``ANONYMATE_DOWNLOADS`` from the ``.env`` of the
working copy, so a test that removes a mismatching data package removed the real one on the
developer's download share, and the EP-online key in that ``.env`` was within reach of tests.
CI has no ``.env``; this makes a local run behave the same.
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _geen_eigen_instellingen(monkeypatch):
    from anonymate import store
    for name in ("ANONYMATE_DOWNLOADS", "ANONYMATE_HOME", "ANONYMATE_GEHEUGEN",
                 store.EPONLINE_KEY_ENV):
        monkeypatch.delenv(name, raising=False)
    eigen = (Path.cwd() / ".env").resolve()
    echt = store.dotenv

    def dotenv(name, files):     # every .env a test makes itself still counts
        return echt(name, [f for f in files if Path(f).resolve() != eigen])

    monkeypatch.setattr(store, "dotenv", dotenv)
