"""Building the population on this computer, with or without EP-online (kladbloknotitie 15,
``docs/werk/ontwerp-ep-online-gui.md``).

Qt-free, so the window, the CLI and later the browser version share the logic and the texts (like
:mod:`anonymate.stappen`). What lives here: checking and keeping the user's own EP-online API key,
working out which steps are needed (:func:`plan`, the one place where the route is chosen), running
them with one progress bar that can be cancelled (:func:`voer_uit`) and all the texts the guidance
shows.

The key goes only to EP-online. It is not in a progress text, an error message, the manifest or
the settings; it is stored only on request, as ``EPONLINE_API_KEY=`` in ``<store>/.env`` (the line
:func:`anonymate.store.ingest_eponline` reads).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import time
import urllib.error
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Callable

from . import datapakket, store as st
from .voortgang import Voortgang, monotoon

EP_AANVRAAG_URL = "https://apikey.ep-online.nl/"

# Reference durations in seconds, only for dividing the bar over the steps and for the first
# estimate. Measured 2026-10-03 with `anonymate ingest pakket` on a clean store (laptop, 8 GB RAM,
# home fibre): package 49-141 s, EP-online download 102 s, reading it 124 s, population 1727 s
# without labels (55 min with labels, but swapping for lack of memory); rounded up a little.
REFERENTIE_S = {"pakket": 150, "ep_download": 120, "ep_inlezen": 150, "populatie": 1800}
RUIMTE_EXTRA_B = 2_000_000_000        # EP-online and the population, on top of the package

# ------------------------------------------------------------------------------------------------
# texts
# ------------------------------------------------------------------------------------------------

UITLEG_EP = ("Voor een echte toets heeft AnonyMate alle woningen in Nederland nodig. Het "
             "datapakket van anonymate.nl bevat BAG en 3D-BAG, maar geen energielabels: die mag "
             "AnonyMate niet doorgeven. Met een eigen, gratis sleutel haalt AnonyMate ze "
             "rechtstreeks bij EP-online (RVO).")
STAPPEN_SLEUTEL = [
    "Open het aanvraagformulier (knop hieronder).",
    "Vul de naam van je organisatie, het type organisatie en je e-mailadres in; het "
    "KvK-nummer is niet verplicht.",
    "Je krijgt een e-mail met een activeringslink; klik die binnen 24 uur aan.",
    "De sleutel staat dan op het scherm en wordt niet gemaild: kopieer hem meteen.",
    "Plak hem hieronder. Een nieuwe sleutel werkt na ongeveer 5 minuten.",
]
SLEUTEL_VERVALT = "Een sleutel die een jaar niet wordt gebruikt, vervalt."
PRIVACY_SLEUTEL = ("De sleutel blijft op deze computer en gaat alleen naar EP-online. AnonyMate "
                   "bewaart hem niet, tenzij je hieronder 'onthouden' aanvinkt; dan staat hij "
                   "in {pad}.")
ZONDER_EP_GEVOLG = ("De toets werkt ook zonder labels. Het woningtype komt dan uit de vorm van het "
                    "pand (3D-BAG) in plaats van uit het label, en signaturen die labeldata "
                    "gebruiken ontbreken. Een aanvaller met toegang tot EP-online weet meer dan "
                    "deze populatie; de toets onderschat het risico dan een beetje.")
KEUZE_SLEUTEL = "Met mijn EP-online-sleutel"
KEUZE_BESTAND = "Ik heb het EP-online-bestand al"
KEUZE_GEEN = "Zonder EP-online"
NIET_BEREIKBAAR = "EP-online is niet bereikbaar; controleer de internetverbinding."
SLEUTEL_ONBEKEND = ("EP-online kent deze sleutel niet. Let op: een nieuwe sleutel werkt pas "
                    "ongeveer 5 minuten na het activeren.")
SLEUTEL_GELDIG = "De sleutel is geldig."
NIETS_TE_DOEN = "Er is niets te doen: de populatie staat al klaar."
DOORLOPEN = ("De computer kan ondertussen gewoon gebruikt worden; laat hem aan staan. Afbreken "
             "kan; de volgende keer gaat AnonyMate verder waar het bleef.")
DOWNLOADS_GESCHAT = "Downloads worden niet gemeten maar geschat."
GEEN_RUIMTE = ("Er is te weinig vrije schijfruimte: {pad} heeft {vrij} vrij en er is {nodig} "
               "nodig. Maak ruimte vrij of kies een andere map met --downloads / --home.")


# ------------------------------------------------------------------------------------------------
# the key
# ------------------------------------------------------------------------------------------------

@dataclass
class Sleutelcontrole:
    geldig: bool | None        # None: cannot be determined (no network)
    melding: str               # plain language, never with the key in it
    bestand: str | None = None  # name of the totaalbestand, when valid


def schoon_sleutel(key: str) -> str:
    """The key as pasted, without spaces and line breaks around (or in) it."""
    return "".join((key or "").split())


def controleer_sleutel(key: str, fetcher=None) -> Sleutelcontrole:
    """Ask EP-online for the DownloadInfo: the same request the download makes. The messages
    are fixed texts, so nothing the server says (or an exception holds) reaches the user."""
    key = schoon_sleutel(key)
    if not key:
        return Sleutelcontrole(False, "Vul eerst de sleutel in.")
    try:
        info = st.eponline_info(key, fetcher)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return Sleutelcontrole(False, SLEUTEL_ONBEKEND)
        return Sleutelcontrole(None, f"EP-online geeft nu een foutmelding (code {e.code}); "
                                     "probeer het later nog eens.")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
        return Sleutelcontrole(None, NIET_BEREIKBAAR)
    except ValueError:                       # the answer was not JSON
        return Sleutelcontrole(False, "EP-online gaf een antwoord dat AnonyMate niet begrijpt.")
    if not isinstance(info, dict) or not info.get("downloadUrl"):
        return Sleutelcontrole(False, "EP-online gaf geen downloadadres bij deze sleutel.")
    return Sleutelcontrole(True, SLEUTEL_GELDIG, info.get("bestandsnaam") or None)


def _env_pad(store) -> Path:
    return Path(store.root) / ".env"


def bewaarde_sleutel(store) -> str | None:
    """The key from the environment variable, else from ``<store>/.env``."""
    return os.environ.get(st.EPONLINE_KEY_ENV) or st.dotenv(st.EPONLINE_KEY_ENV,
                                                             [_env_pad(store)])


def gevonden_sleutel(store) -> str | None:
    """The key as :func:`anonymate.store.ingest_eponline` finds it (environment variable, then
    ``./.env``, then ``<store>/.env``), for the command line."""
    return os.environ.get(st.EPONLINE_KEY_ENV) or st.dotenv(
        st.EPONLINE_KEY_ENV, [Path.cwd() / ".env", _env_pad(store)])


def _regels_zonder_sleutel(path: Path) -> list[str]:
    if not path.is_file():
        return []
    keep = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        k, sep, _ = line.strip().partition("=")
        if sep and k.strip() == st.EPONLINE_KEY_ENV and not k.lstrip().startswith("#"):
            continue
        keep.append(line)
    return keep


def bewaar_sleutel(store, key: str) -> Path:
    """Write (or replace) only the ``EPONLINE_API_KEY`` line of ``<store>/.env``; other lines
    stay. Deliberately not ``./.env``: the window writes only in its own store."""
    path = _env_pad(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = _regels_zonder_sleutel(path) + [f"{st.EPONLINE_KEY_ENV}={schoon_sleutel(key)}"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)               # no effect on Windows; the profile folder is private
    except OSError:
        pass
    return path


def vergeet_sleutel(store) -> None:
    """Remove the key line from ``<store>/.env`` (and the file when nothing else is in it)."""
    path = _env_pad(store)
    if not path.is_file():
        return
    lines = _regels_zonder_sleutel(path)
    if any(x.strip() for x in lines):
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        path.unlink()


# ------------------------------------------------------------------------------------------------
# what is there, and what is needed
# ------------------------------------------------------------------------------------------------

@dataclass
class Toestand:
    """What is already local; quick to determine, no network."""
    populatie: bool
    populatie_met_labels: bool     # built with EP-online, from the user's own store or sources
    pakket_zip: bool               # zip and manifest in downloads (sha256 is checked on use)
    ep_parquet: bool               # raw/ep_online.parquet
    ep_versie: str | None
    woningen: int | None = None
    pakket_datum: str | None = None


def toestand(store) -> Toestand:
    m = store.manifest()
    bronnen = m.get("sources", {})
    populatie = store.population_path.exists()
    pakket = bronnen.get("datapakket")
    labels = (pakket.get("ep_online") == "eigen opslag") if pakket else "ep-online" in bronnen
    ep = store.raw / "ep_online.parquet"
    datum = None
    if pakket and pakket.get("version"):
        try:
            datum = f"{date.fromisoformat(str(pakket['version'])[:10]):%d-%m-%Y}"
        except ValueError:
            datum = str(pakket["version"])
    return Toestand(
        populatie=populatie, populatie_met_labels=populatie and labels,
        pakket_zip=((store.downloads / datapakket.ZIP_NAME).exists()
                    and (store.downloads / datapakket.MANIFEST_NAME).exists()),
        ep_parquet=ep.exists(),
        ep_versie=str(bronnen["ep-online"].get("version")) if ep.exists()
        and "ep-online" in bronnen else None,
        woningen=(m.get("population") or {}).get("rows") if populatie else None,
        pakket_datum=datum)


def aantal_tekst(n: int) -> str:
    """6,2 miljoen / 12.345 (Dutch notation)."""
    if n >= 1_000_000:
        return f"{n / 1e6:.1f}".replace(".", ",") + " miljoen"
    return f"{n:,}".replace(",", ".")


def toestand_regel(t: Toestand) -> str:
    """The one line about the population: what it is and whether it has EP-online labels."""
    if not t.populatie:
        return "Nog geen populatie op deze computer"
    delen = [f"{aantal_tekst(t.woningen)} woningen" if t.woningen else "Populatie aanwezig"]
    if t.pakket_datum:
        delen.append(f"datapakket van {t.pakket_datum}")
    if t.populatie_met_labels:
        publicatie = re.search(r"publicatie ([^,]+)", t.ep_versie or "")
        delen.append("met EP-online" + (f" (publicatie {publicatie[1]})" if publicatie else ""))
    else:
        delen.append("zonder EP-online-labels")
    return ", ".join(delen)


class Bron(Enum):
    """Where the EP data come from."""
    GEEN = "geen"          # go on without EP-online
    SLEUTEL = "sleutel"    # route B: own key, own download
    BESTAND = "bestand"    # route B: a totaalbestand the user downloaded
    PAKKET = "pakket"      # route A: already in the package (later)


@dataclass
class Stap:
    naam: str                          # "EP-online downloaden"
    gewicht_s: float                   # reference duration, for the bar and the first estimate
    doe: Callable[[Voortgang], None]
    klaar: bool = False                # already done: shown in the overview, skipped by plan


def ep_route(manifest) -> Bron | None:
    """The route the published manifest.json offers for EP data, or None (then route B).

    Read only; nothing writes these fields yet. Agreed for later: ``"ep_online": {"in_pakket":
    true}`` (route A) or ``"varianten": {"ep": {"naam", "manifest", "toegang": "open"}}`` (also
    A). ``"toegang": "sleutel"`` is route C: its step does not exist yet, so None, and the user
    gets route B. Anything else, including today's text in ``"ep_online"``, gives None."""
    if not isinstance(manifest, dict):
        return None
    ep = manifest.get("ep_online")
    if isinstance(ep, dict) and ep.get("in_pakket") is True:
        return Bron.PAKKET
    variant = (manifest.get("varianten") or {}).get("ep") if isinstance(
        manifest.get("varianten"), dict) else None
    if isinstance(variant, dict) and variant.get("naam") and variant.get("manifest") \
            and variant.get("toegang") == "open":
        return Bron.PAKKET
    return None


class Geannuleerd(Exception):
    """The user stopped the build."""


def _mb(n: float) -> str:
    return f"{n / 1e6:,.0f} MB".replace(",", ".") if n < 1e9 else f"{n / 1e9:.1f} GB".replace(
        ".", ",")


def _bytes_melder(v: Voortgang, basis: str):
    return lambda done, total: v.set(done / total if total else None, f"{basis} · {_mb(done)}")


def _poging_melder(v: Voortgang, basis: str):
    """Only the messages about a connection that dropped (the bytes tell the rest)."""
    return lambda tekst: v.update(0, f"{basis} · {tekst}") if "poging" in tekst else None


def _fractie_melder(v: Voortgang, basis: str):
    return lambda f: v.set(f, f"{basis} · {round(100 * f)}%")


def _zonder_sleutel(doe, key: str):
    """``doe`` that never lets the key out in an exception text."""
    def veilig(v):
        try:
            doe(v)
        except Geannuleerd:
            raise
        except Exception as e:  # noqa: BLE001 (re-raised without the key)
            tekst = str(e)
            if key and key in tekst:
                raise RuntimeError(tekst.replace(key, "…")) from None
            raise
    return veilig


def _controleer_pakket(store) -> None:
    """The zip in downloads against the published manifest next to it; a wrong zip is removed."""
    zip_path, manifest = (store.downloads / datapakket.ZIP_NAME,
                          store.downloads / datapakket.MANIFEST_NAME)
    if manifest.exists():
        try:
            datapakket.verify(zip_path, manifest)
        except ValueError as e:
            zip_path.unlink(missing_ok=True)
            raise ValueError(f"Het gedownloade datapakket klopt niet ({e}). Het is verwijderd; "
                             "probeer het opnieuw.") from None


def plan(store, toestand: Toestand, bron: Bron, *, key: str | None = None,
         bestand: str | Path | None = None, pakket_manifest: dict | None = None,
         pakket: str | Path | None = None, ep_zip: str | None = None,
         fetcher=None, downloader=None) -> list[Stap]:
    """The steps still to do for ``bron``, in order. The only place where the route is chosen.

    ``pakket`` installs that package (zip or folder) instead of the downloaded one;
    ``ep_zip`` is the file name from :func:`controleer_sleutel` (a download that is there already
    is skipped); ``fetcher`` and ``downloader`` replace the network. ``pakket_manifest`` is the
    published manifest.json the window fetched; :func:`ep_route` reads the route from it."""
    return [s for s in overzicht(store, toestand, bron, key=key, bestand=bestand,
                                 pakket_manifest=pakket_manifest, pakket=pakket, ep_zip=ep_zip,
                                 fetcher=fetcher, downloader=downloader) if not s.klaar]


def overzicht(store, toestand: Toestand, bron: Bron, *, key: str | None = None,
              bestand: str | Path | None = None, pakket_manifest: dict | None = None,
              pakket: str | Path | None = None, ep_zip: str | None = None,
              fetcher=None, downloader=None) -> list[Stap]:
    """All steps of :func:`plan`, the ones that are done already marked ``klaar`` (the window
    shows them greyed)."""
    if bron is Bron.PAKKET:
        if ep_route(pakket_manifest) is not Bron.PAKKET:
            raise ValueError("het datapakket bevat geen EP-online")
        raise NotImplementedError("route A (EP-online in het datapakket) is nog niet gebouwd")
    if bron is Bron.SLEUTEL and not schoon_sleutel(key or ""):
        raise ValueError("geen EP-online-sleutel opgegeven")
    if bron is Bron.BESTAND and not (bestand and Path(bestand).exists()):
        raise ValueError("het EP-online-bestand bestaat niet")
    key = schoon_sleutel(key or "")
    ctx: dict = {}
    if bron is Bron.GEEN and toestand.populatie:
        return []                                  # nothing to add to an existing population

    def netwerk():                                 # looked up late: tests replace the module's
        return fetcher or st.fetch, downloader or st.download

    def pakket_stap(v):
        base = v.text
        st.download_datapakket(store, progress=_poging_melder(v, base),
                               on_bytes=_bytes_melder(v, base), fetcher=fetcher,
                               downloader=downloader)
        ctx["gecontroleerd"] = True

    def ep_download(v):
        base = v.text
        fetch_, download_ = netwerk()
        info = st.eponline_info(key, fetch_)
        if not info.get("downloadUrl"):
            raise RuntimeError("EP-online gaf geen downloadadres bij deze sleutel")
        doel = store.downloads / (info.get("bestandsnaam") or "ep-online-totaal.zip")
        if not doel.exists():                      # a download is renamed only when complete
            download_(info["downloadUrl"], doel, progress=_poging_melder(v, base),
                      on_bytes=_bytes_melder(v, base))

    def ep_inlezen(v):
        fetch_, _ = netwerk()
        fractie = _fractie_melder(v, v.text)
        if bron is Bron.SLEUTEL:
            st.ingest_eponline(store, api_key=key, fetcher=fetch_, fraction=fractie)
        else:
            st.ingest_eponline(store, bestand, fraction=fractie)

    def populatie(v):
        if pakket is None and not ctx.get("gecontroleerd"):
            _controleer_pakket(store)
        datapakket.install(pakket or store.downloads / datapakket.ZIP_NAME, store,
                           fraction=_fractie_melder(v, v.text))

    stappen = []
    if pakket is None:
        stappen.append(Stap("Datapakket downloaden en controleren", REFERENTIE_S["pakket"],
                            pakket_stap, klaar=toestand.pakket_zip))
    if bron is Bron.SLEUTEL:
        al = bool(ep_zip) and (store.downloads / ep_zip).exists()
        stappen.append(Stap("EP-online downloaden", REFERENTIE_S["ep_download"],
                            _zonder_sleutel(ep_download, key), klaar=al))
    if bron in (Bron.SLEUTEL, Bron.BESTAND):
        stappen.append(Stap("EP-online inlezen", REFERENTIE_S["ep_inlezen"],
                            _zonder_sleutel(ep_inlezen, key)))
    stappen.append(Stap("Populatie en signaturen uitrekenen", REFERENTIE_S["populatie"],
                        _zonder_sleutel(populatie, key)))
    return stappen


# ------------------------------------------------------------------------------------------------
# running, cancelling, space
# ------------------------------------------------------------------------------------------------

def voer_uit(stappen: list[Stap], progress, *, stop: threading.Event | None = None,
             klok=time.monotonic) -> None:
    """Run the steps behind one progress callback ``progress(fraction, text)``: the bar is divided
    by the steps' ``gewicht_s``, the text is "2 van 4: EP-online downloaden · 312 MB".

    Every message first checks ``stop``; set, it raises :class:`Geannuleerd`, so any function
    that reports progress stops at its next message without knowing about cancelling. What stays
    behind is a ``.part`` (resumed later) or a ``.parquet.part`` (overwritten later);
    ``population.parquet`` and ``raw/ep_online.parquet`` are replaced only at the end."""
    def melding(fraction, text):
        if stop is not None and stop.is_set():
            raise Geannuleerd("afgebroken")
        progress(fraction, text)

    top = Voortgang(None, monotoon(melding), clock=klok)
    gewichten = [max(s.gewicht_s, 0.0) for s in stappen]
    if not sum(gewichten):
        gewichten = [1.0] * len(stappen)
    lo = 0.0
    for i, (stap, gewicht) in enumerate(zip(stappen, gewichten), 1):
        if stop is not None and stop.is_set():
            raise Geannuleerd("afgebroken")
        hi = lo + gewicht / sum(gewichten)
        v = top.stage(lo, hi, text=f"{i} van {len(stappen)}: {stap.naam}")
        v.set(0.0)
        stap.doe(v)
        v.set(1.0)
        lo = hi
    top.set(1.0, "Klaar")


def _gb(n: float) -> str:
    return f"{n / 1e9:.1f} GB".replace(".", ",")


def benodigde_ruimte(pakket_manifest: dict | None) -> int:
    """Bytes needed: the zip twice (zip and unpacked) plus room for EP-online and the population."""
    zip_bytes = int(((pakket_manifest or {}).get("zip") or {}).get("bytes") or 0)
    return 2 * zip_bytes + RUIMTE_EXTRA_B


def haal_pakket_manifest(fetcher=None) -> dict | None:
    """The published manifest.json of the datapakket (small); None when it cannot be fetched.
    Gives :func:`ep_route` and :func:`controleer_ruimte` what they need."""
    try:
        manifest = json.loads((fetcher or st.fetch)(st.DATAPAKKET_MANIFEST_URL))
    except Exception:  # noqa: BLE001 (a nicety; the build fetches it again and then fails loudly)
        return None
    return manifest if isinstance(manifest, dict) else None


def ruimte_regel(store, pakket_manifest: dict | None) -> str:
    """What the build needs on disk and what is free, also when it fits, e.g. "Schijfruimte:
    ongeveer 2,8 GB nodig; vrij: 41,2 GB (<map>)"; one entry per folder."""
    vrij = []
    for pad in dict.fromkeys((store.root, store.downloads)):
        try:
            vrij.append(f"{_gb(shutil.disk_usage(pad).free)} ({pad})")
        except OSError:
            continue
    tekst = f"Schijfruimte: ongeveer {_gb(benodigde_ruimte(pakket_manifest))} nodig"
    return tekst + (f"; vrij: {', '.join(vrij)}" if vrij else "")


def controleer_ruimte(store, pakket_manifest: dict | None) -> str | None:
    """A message when a folder the build writes to has too little room, else None; before the
    start, not halfway."""
    nodig = benodigde_ruimte(pakket_manifest)
    for pad in (store.downloads, store.root):
        vrij = shutil.disk_usage(pad).free
        if vrij < nodig:
            return GEEN_RUIMTE.format(pad=pad, vrij=_gb(vrij), nodig=_gb(nodig))
    return None
