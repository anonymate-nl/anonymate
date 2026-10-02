"""Progress of long operations, the same in the desktop window, the CLI and the browser version.

Qt-free and without any knowledge of time: an operation reports *how far it is* (a fraction 0..1
and a text) through ``progress(fraction, text)``; the user interface adds the clock. The window
and the page both compute "nog ongeveer m:ss" (the time left, never the time elapsed) from that
fraction and the seconds elapsed, with :class:`Schatter`. The page has a small port of it
(``Schatter`` in web/app.js); keep the two equal (tests/test_voortgang.py compares them).

Use :class:`Voortgang` inside an operation, like tqdm::

    with Voortgang(len(items), progress, text="woningen") as v:
        for item in items:
            ...
            v.update()

``progress=None`` makes every call a no-op, so an operation stays callable without a listener.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

ESTIMATE_FROM = 0.05      # no estimate of the time left before this fraction is done
MAX_PER_SECOND = 5        # callbacks per second at most


def clock(seconds: float) -> str:
    """m:ss."""
    s = max(int(seconds), 0)
    return f"{s // 60}:{s % 60:02d}"


ALMOST_DONE = 3.0         # below this many seconds left: "bijna klaar", never "0:00"
SMOOTHING = 0.3           # weight of a new estimate of the finishing time (exponential smoothing)


def _rounded(seconds: float) -> float:
    """Round to steps that hide the jitter: 5 s below a minute, 10 s above."""
    step = 5 if seconds < 60 else 10
    return max(round(seconds / step) * step, step)


def remaining_text(remaining_s: float | None) -> str:
    """"nog ongeveer m:ss" for the time left; "schatting volgt…" when there is no estimate yet
    and "bijna klaar" when there are only seconds left (never "0:00" while still running)."""
    if remaining_s is None:
        return "schatting volgt…"
    if remaining_s < ALMOST_DONE:
        return "bijna klaar"
    return f"nog ongeveer {clock(_rounded(remaining_s))}"


class Schatter:
    """Estimates the time left from (fraction, elapsed seconds), smoothed so the text does not
    jump: the moment of finishing is smoothed exponentially and the time left counts down
    against the clock between reports. The page has a port (``Schatter`` in web/app.js)."""

    def __init__(self):
        self._finish: float | None = None       # smoothed moment of finishing, in elapsed seconds

    def remaining(self, fraction: float | None, elapsed_s: float) -> float | None:
        if fraction is not None and fraction > ESTIMATE_FROM:
            raw = elapsed_s + elapsed_s * (1 - fraction) / fraction
            self._finish = raw if self._finish is None else                 SMOOTHING * raw + (1 - SMOOTHING) * self._finish
        if self._finish is None:
            return None
        return max(self._finish - elapsed_s, 0.0)

    def text(self, fraction: float | None, elapsed_s: float) -> str:
        """The time part of the progress line; "" without a fraction (only the label then)."""
        if fraction is None:
            return ""
        return remaining_text(self.remaining(fraction, elapsed_s))


def eta_text(fraction: float | None, elapsed_s: float) -> str:
    """The unsmoothed time part: "nog ongeveer m:ss" once ``fraction`` is beyond 5%,
    "schatting volgt…" before that, and "" when the fraction is unknown. No elapsed time."""
    return Schatter().text(fraction, elapsed_s)


def monotoon(progress):
    """``progress`` wrapped so the fraction never goes back (an operation that does a part twice
    would otherwise make the bar jump back); None stays None."""
    if progress is None:
        return None
    top = [0.0]

    def report(fraction, text):
        if fraction is not None:
            top[0] = max(top[0], fraction)
            fraction = top[0]
        progress(fraction, text)
    return report


class Voortgang:
    """Reports the progress of one operation to ``progress(fraction, text)``.

    ``total`` is the number of steps when known (then :meth:`update` reports a fraction), else
    None (the callback then gets ``fraction=None``: "busy, no idea how far"). Calls are throttled
    to ``MAX_PER_SECOND``; the first, the last (fraction 1) and text changes at the start of a
    stage always get through. ``lo``/``hi`` map this operation into a part of a bigger one:
    ``Voortgang(10, progress, lo=0.2, hi=0.8)`` reports fractions between 0.2 and 0.8.
    """

    def __init__(self, total: int | None = None, progress=None, *, text: str = "",
                 lo: float = 0.0, hi: float = 1.0, clock=time.monotonic):
        self.total = total
        self.progress = progress
        self.text = text
        self.lo, self.hi = lo, hi
        self.n = 0
        self._clock = clock
        self._last: float | None = None
        self._interval = 1.0 / MAX_PER_SECOND

    # -- reporting -------------------------------------------------------------------------
    def _emit(self, fraction: float | None, text: str | None, force: bool = False) -> None:
        if self.progress is None:
            return
        now = self._clock()
        if not force and self._last is not None and now - self._last < self._interval:
            return
        self._last = now
        if fraction is not None:
            fraction = self.lo + (self.hi - self.lo) * min(max(fraction, 0.0), 1.0)
        self.progress(fraction, self.text if text is None else text)

    def update(self, n: int = 1, text: str | None = None) -> None:
        """``n`` more steps done (optionally with a new text)."""
        self.n += n
        if text is not None:
            self.text = text
        frac = None if not self.total else self.n / self.total
        self._emit(frac, None, force=bool(self.total) and self.n >= self.total)

    def set(self, fraction: float | None, text: str | None = None) -> None:
        """Report an explicit fraction (0..1) and text."""
        if text is not None:
            self.text = text
        self._emit(fraction, None, force=fraction is not None and fraction >= 1.0)

    def stage(self, lo: float, hi: float, total: int | None = None, text: str = "") -> "Voortgang":
        """A part of this operation (from ``lo`` to ``hi`` of it) as an operation of its own."""
        span = self.hi - self.lo
        return Voortgang(total, self.progress, text=text or self.text,
                         lo=self.lo + span * lo, hi=self.lo + span * hi, clock=self._clock)

    def callback(self):
        """This (part of an) operation as a plain ``progress(fraction, text)`` function, for code
        that takes a callback: a fraction 0..1 of it is mapped into ``lo``..``hi``."""
        return lambda fraction, text=None: self.set(fraction, text)

    # -- context manager -------------------------------------------------------------------
    def __enter__(self) -> "Voortgang":
        self._emit(0.0 if self.total else None, None, force=True)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self._emit(1.0, None, force=True)


def klaar_rond(remaining_s: float | None, now: datetime) -> str:
    """"klaar rond 14:35" for the moment of finishing (rounded to 5 minutes, "morgen" when it is
    past midnight); "" without an estimate. For long operations, where a clock time says more than
    "nog ongeveer 3:20:00"."""
    if remaining_s is None:
        return ""
    t = now + timedelta(seconds=remaining_s)
    uur = t.replace(minute=0, second=0, microsecond=0)
    t = uur + timedelta(minutes=round((t - uur).total_seconds() / 300) * 5)
    dag = "morgen " if t.date() != now.date() else ""
    return f"klaar rond {dag}{t:%H:%M}"


def duur_tekst(seconds: float) -> str:
    """A duration in words, rounded to 5 minutes: "ongeveer 1 uur 10 minuten"."""
    minutes = max(round(seconds / 300) * 5, 5)
    uren, rest = divmod(minutes, 60)
    delen = ([f"{uren} uur"] if uren else []) + ([f"{rest} minuten"] if rest else [])
    return "ongeveer " + " ".join(delen)


def vooraf_schatting(stappen) -> str:
    """The estimate before anything is measured: the summed reference durations (``gewicht_s``) of
    the steps, "ongeveer 1 uur 10 minuten (schatting)"; "" for no steps."""
    totaal = sum(s.gewicht_s for s in stappen)
    return f"{duur_tekst(totaal)} (schatting)" if totaal > 0 else ""
