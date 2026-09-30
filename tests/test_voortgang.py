"""The shared progress helper: throttling, stages, and the text every window shows."""
import re
from pathlib import Path

import pytest

from anonymate.voortgang import (ALMOST_DONE, ESTIMATE_FROM, SMOOTHING, Schatter, Voortgang,
                                 clock, eta_text, monotoon, remaining_text)

APP_JS = Path(__file__).parents[1] / "web" / "app.js"


def test_clock_is_minutes_and_two_digit_seconds():
    assert [clock(s) for s in (0, 5.9, 65, 600, 3725)] == ["0:00", "0:05", "1:05", "10:00", "62:05"]


def test_eta_text_shows_the_time_left_and_never_the_time_elapsed():
    assert eta_text(None, 12) == ""                       # unknown fraction: the label only
    assert eta_text(0.05, 12) == "schatting volgt…"
    assert eta_text(0.5, 60) == "nog ongeveer 1:00"
    assert eta_text(0.25, 30) == "nog ongeveer 1:30"
    assert eta_text(0.9, 35) == "nog ongeveer 0:05"        # 3.9 s left, in steps of 5
    assert eta_text(1.0, 61) == "bijna klaar"              # never 0:00 while running
    for f in (None, 0.03, 0.4, 0.99):
        assert "bezig" not in eta_text(f, 100)


def test_the_estimate_is_rounded_smoothed_and_counts_down():
    assert remaining_text(None) == "schatting volgt…"
    assert remaining_text(2.9) == "bijna klaar"
    assert remaining_text(37) == "nog ongeveer 0:35"
    assert remaining_text(93) == "nog ongeveer 1:30"
    s = Schatter()
    assert s.text(0.1, 10) == "nog ongeveer 1:30"        # 90 s left
    assert s.remaining(0.2, 20) == pytest.approx(80.0)    # same finishing time (100 s): counts down
    # a wild new estimate moves the finishing time only a bit
    s2 = Schatter()
    s2.remaining(0.5, 10)                                 # finishes at 20
    assert s2.remaining(0.6, 12) == pytest.approx(0.3 * 20 + 0.7 * 20 - 12)
    assert s2.remaining(0.9, 30) < 3 and s2.text(0.9, 30) == "bijna klaar"


def test_the_page_has_the_same_formula():
    """web/app.js has a port (Schatter); the constants and the text pieces must match."""
    js = APP_JS.read_text(encoding="utf-8")
    body = js[js.index("function resttekst"):js.index("function maakVoortgang")]
    assert f"const ETA_VANAF = {ESTIMATE_FROM}" in js
    assert f"const BIJNA_KLAAR = {ALMOST_DONE}" in js and f"const GLADDEN = {SMOOTHING}" in js
    assert "nog ongeveer" in body and "schatting volgt…" in body and "bijna klaar" in body
    assert "elapsed + elapsed * (1 - fraction) / fraction" in body
    assert "fraction > ETA_VANAF" in body and "rest < 60 ? 5 : 10" in body
    assert "bezig" not in body and "elapsed}" not in body
    assert "Math.floor(sec / 60)" in js and 'padStart(2, "0")' in js
    assert "bezig`" not in js                           # nowhere an elapsed-time line


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_voortgang_throttles_and_always_reports_the_last_step():
    seen, t = [], Clock()
    with Voortgang(100, lambda f, x: seen.append((f, x)), text="rijen", clock=t) as v:
        for _ in range(100):
            t.t += 0.01                    # 100 updates in one second: at most ~5 callbacks
            v.update()
    assert 5 <= len(seen) <= 9
    assert seen[0] == (0.0, "rijen") and seen[-1][0] == 1.0
    fractions = [f for f, _ in seen]
    assert fractions == sorted(fractions)


def test_voortgang_without_total_reports_none_and_stages_map_a_range():
    seen, t = [], Clock()
    v = Voortgang(None, lambda f, x: seen.append((f, x)), clock=t)
    v.update(text="bezig met iets")
    assert seen == [(None, "bezig met iets")]
    seen.clear()
    top = Voortgang(None, lambda f, x: seen.append((round(f, 3), x)), clock=t)
    part = top.stage(0.5, 1.0, 4, "helft")
    for _ in range(4):
        t.t += 1
        part.update()
    assert seen[-1] == (1.0, "helft") and seen[0][0] == 0.625
    assert top.stage(0.0, 0.2).callback() is not None


def test_no_callback_is_a_no_op_and_monotoon_never_goes_back():
    Voortgang(3, None).update()
    assert monotoon(None) is None
    seen = []
    m = monotoon(lambda f, x: seen.append(f))
    for f in (0.2, 0.6, 0.3, None, 0.9):
        m(f, "x")
    assert seen == [0.2, 0.6, 0.6, None, 0.9]


def test_long_operations_take_a_progress_callback():
    import inspect

    from anonymate import kaart, publicatie, stappen, weerspoor, web
    from anonymate.generalize import suggest
    for fn in (weerspoor.investigate, kaart.MapData.cell_stats, kaart.noisy_cells,
               stappen.add_weather, stappen.locations, publicatie.explore, suggest,
               web.open_practice, web.run, web.suggest, web.map_cell, web.weather, web.uhi,
               web.trace):
        assert inspect.signature(fn).parameters["progress"].default is None


@pytest.mark.parametrize("cmd", ["open_practice", "run", "suggest", "map_cell", "weather", "uhi",
                                 "trace"])
def test_the_worker_hands_every_long_command_a_progress_callback(cmd):
    js = (Path(__file__).parents[1] / "web" / "worker.js").read_text(encoding="utf-8")
    case = js[js.index(f'case "{cmd}"'):]
    case = case[:case.index("case ", 10)] if "case " in case[10:] else case
    assert "voortgang(id)" in case or "progress" in case
    assert re.search(r'postMessage\(\{ type: "progress", id', js)
