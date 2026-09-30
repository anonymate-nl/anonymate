"""Progress of long operations, the same in the desktop window, the CLI and the browser version.

Qt-free and without any knowledge of time: an operation reports *how far it is* (a fraction 0..1
and a text) through ``progress(fraction, text)``; the user interface adds the clock. The window
and the page both compute "m:ss bezig · nog ongeveer m:ss" from that fraction and the seconds
elapsed, by :func:`eta_text`. The page has a small port of it (``etaText`` in web/app.js); keep
the two equal (tests/test_voortgang.py compares the constants).

Use :class:`Voortgang` inside an operation, like tqdm::

    with Voortgang(len(items), progress, text="woningen") as v:
        for item in items:
            ...
            v.update()

``progress=None`` makes every call a no-op, so an operation stays callable without a listener.
"""
from __future__ import annotations

import time

ESTIMATE_FROM = 0.05      # no estimate of the time left before this fraction is done
MAX_PER_SECOND = 5        # callbacks per second at most


def clock(seconds: float) -> str:
    """m:ss."""
    s = max(int(seconds), 0)
    return f"{s // 60}:{s % 60:02d}"


def eta_text(fraction: float | None, elapsed_s: float) -> str:
    """"m:ss bezig · nog ongeveer m:ss"; the estimate only once ``fraction`` is beyond 5%, and
    just "m:ss bezig" before that (or without a fraction)."""
    parts = [f"{clock(elapsed_s)} bezig"]
    if fraction is not None and fraction > ESTIMATE_FROM:
        parts.append(f"nog ongeveer {clock(elapsed_s * (1 - fraction) / fraction)}")
    return " · ".join(parts)


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

