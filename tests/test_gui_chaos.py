"""Monkey test: press the window's buttons in many orders and combinations. Every action must
either work or end in a message for the user; no exception may escape (in the Windows program an
escaped exception is silent, and the window just stops doing things)."""
import itertools
import os
import sys
import time

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from anonymate import Population, synthetic  # noqa: E402

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "docs", "voorbeeld", "woningen.csv")


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def population():
    return Population.from_dataframe(synthetic.population(20_000, seed=4))


def settle(app, w, timeout=60):
    end = time.time() + timeout
    while any(t.isRunning() for t in w._threads) and time.time() < end:
        app.processEvents()
        time.sleep(0.02)
    for _ in range(5):
        app.processEvents()


ACTIONS = ["assess", "explore", "suggest", "weather", "save", "lock", "sig_on", "sig_off",
           "koppel_empty", "weather_h3", "weather_station", "uhi_on", "reload", "go_weather"]


def run(w, action, tmp_path):
    if action == "assess":
        w.run_assess()
    elif action == "explore":
        w.run_explore()
    elif action == "suggest":
        w.run_suggest()
    elif action == "weather":
        w.apply_weather()
    elif action == "save":
        w.save()
    elif action == "lock":
        w.lock_norm()
    elif action == "sig_on":
        w.sig_on.setChecked(True)
    elif action == "sig_off":
        w.sig_on.setChecked(False)
    elif action == "koppel_empty":
        w.koppel.setText("")
    elif action == "weather_h3":
        w.w_h3.setChecked(True)
    elif action == "weather_station":
        w.w_station.setChecked(True)
    elif action == "uhi_on":
        w.w_uhi.setChecked(True)
    elif action == "reload":
        w.load(EXAMPLE)
    elif action == "go_weather":
        w.go(4)


@pytest.mark.parametrize("seed", range(6))
def test_no_action_sequence_raises(app, population, tmp_path, monkeypatch, seed):
    import random

    import anonymate.gui as g
    messages, escaped = [], []
    monkeypatch.setattr(g.QMessageBox, "warning", lambda *a, **k: messages.append(a[2]))
    monkeypatch.setattr(g.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(g.QFileDialog, "getExistingDirectory",
                        lambda *a, **k: str(tmp_path / f"uit{seed}"))
    monkeypatch.setattr(sys, "excepthook", lambda *exc: escaped.append(exc))
    w = g.MainWindow(population_factory=lambda: population)
    w.load(EXAMPLE)
    rng = random.Random(seed)
    for action in rng.choices(ACTIONS, k=25):
        try:
            run(w, action, tmp_path)
        except Exception as e:  # noqa: BLE001
            escaped.append((action, e))
        settle(app, w)
    assert not escaped, escaped
    # every message is readable Dutch, not a bare Python error
    for m in messages:
        assert not m.startswith(("KeyError", "AttributeError", "TypeError", "IndexError")), m


def test_every_single_action_on_a_fresh_window(app, population, tmp_path, monkeypatch):
    import anonymate.gui as g
    monkeypatch.setattr(g.QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(g.QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(g.QFileDialog, "getExistingDirectory", lambda *a, **k: "")
    for loaded, action in itertools.product((False, True), ACTIONS):
        w = g.MainWindow(population_factory=lambda: population)
        if loaded:
            w.load(EXAMPLE)
        run(w, action, tmp_path)
        settle(app, w)
