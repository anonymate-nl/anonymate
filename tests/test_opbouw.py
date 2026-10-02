"""Building the population with the user's own EP-online key (anonymate.opbouw): the key check,
keeping the key, the plan, running and cancelling, the time texts. No network: the fetcher and the
downloader are fakes, the datapakket and the EP-online zip are small ones made here."""
from __future__ import annotations

import io
import json
import shutil
import threading
import urllib.error
import zipfile
from collections import namedtuple
from datetime import datetime

import pandas as pd
import pytest

from anonymate import datapakket, opbouw, store as st
from anonymate.opbouw import Bron, Toestand
from anonymate.voortgang import Schatter, klaar_rond, vooraf_schatting
from tests.test_datapakket import _population

KEY = "GEHEIM-sleutel-0123456789"
EP_NAAM = "v20260901_totaal.zip"
EP_HEAD = ("PublicatieDatum;01-09-2026\n"
           "Pand_opnamedatum;Pand_registratiedatum;Pand_postcode;Pand_huisnummer;"
           "Pand_bagverblijfsobjectid;Pand_energieklasse;Pand_gebouwklasse;Pand_gebouwtype;"
           "Pand_gebouwsubtype;Pand_energieindex\n")


@pytest.fixture(autouse=True)
def hermetic(tmp_path, monkeypatch):
    """Never the developer's own .env (with a real key) or environment."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(st.EPONLINE_KEY_ENV, raising=False)
    monkeypatch.delenv("ANONYMATE_DOWNLOADS", raising=False)


class Wereld:
    """A fake internet: the published datapakket, EP-online's DownloadInfo and the EP zip."""

    def __init__(self, tmp_path):
        self.pkg = datapakket.make(_population(tmp_path), tmp_path / "pakket", batch_rows=250)
        self.pub = tmp_path / "publicatie"
        self.manifest = datapakket.publish(self.pkg, self.pub)
        ids = pd.read_parquet(self.pkg / "woningen.parquet")["vbo_id__str"].head(50)
        rows = "".join(f"20240101;20240201;8011AB;{i};{vbo};C;W;Rijwoning;tussen;1,4\n"
                       for i, vbo in enumerate(ids, 1))
        self.ep_zip = tmp_path / "ep.zip"
        with zipfile.ZipFile(self.ep_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("totaal.csv", EP_HEAD + rows)
        self.ids = list(ids)
        self.aanroepen: list[str] = []
        self.sleutel_fout: Exception | None = None

    def fetcher(self, url, **kw):
        self.aanroepen.append(url)
        if url == st.EPONLINE_URL:
            if self.sleutel_fout:
                raise self.sleutel_fout
            assert kw["headers"]["Authorization"] == KEY
            return json.dumps({"bestandsnaam": EP_NAAM, "downloadUrl": "https://ep.test/totaal",
                               "geldigTotEnMet": "2026-12-31"}).encode()
        assert url == st.DATAPAKKET_MANIFEST_URL
        return (self.pub / "manifest.json").read_bytes()

    def downloader(self, url, dest, *, progress=None, on_bytes=None, **kw):
        self.aanroepen.append(url)
        bron = self.pub / datapakket.ZIP_NAME if url == st.DATAPAKKET_URL else self.ep_zip
        data = bron.read_bytes()
        dest.parent.mkdir(parents=True, exist_ok=True)
        for i in range(1, 5):                      # four chunks
            if on_bytes:
                on_bytes(len(data) * i // 4, len(data))
        dest.write_bytes(data)
        return dest

    def plan(self, store, bron, **kw):
        return opbouw.plan(store, opbouw.toestand(store), bron, fetcher=self.fetcher,
                           downloader=self.downloader, pakket_manifest=self.manifest, **kw)


class Klok:
    """A clock that is a second further at every look: Voortgang then never throttles."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 1.0
        return self.t


@pytest.fixture
def wereld(tmp_path):
    return Wereld(tmp_path)


@pytest.fixture
def store(tmp_path):
    return st.Store.open(tmp_path / "opslag")


# -- the key ----------------------------------------------------------------------------------

def _http(code, body=""):
    return urllib.error.HTTPError(st.EPONLINE_URL, code, body, {}, None)


def test_a_valid_key_is_recognised_with_the_name_of_the_file(wereld):
    c = opbouw.controleer_sleutel(f"  {KEY}\r\n", wereld.fetcher)    # pasted with spaces around
    assert c.geldig is True and c.bestand == EP_NAAM


@pytest.mark.parametrize("fout,geldig", [
    (_http(401, f"sleutel {KEY} onbekend"), False),
    (_http(403), False),
    (_http(503), None),
    (urllib.error.URLError(f"geen verbinding met {KEY}"), None),
    (TimeoutError(f"time-out {KEY}"), None),
    (ValueError(f"onleesbaar {KEY}"), False),
])
def test_a_key_that_fails_gives_a_plain_message_without_the_key(wereld, fout, geldig):
    wereld.sleutel_fout = fout
    c = opbouw.controleer_sleutel(KEY, wereld.fetcher)
    assert c.geldig is geldig and c.melding and KEY not in c.melding
    if geldig is False and isinstance(fout, urllib.error.HTTPError):
        assert "5 minuten" in c.melding


def test_odd_answers_from_ep_online_are_not_valid():
    for body in (b"<html>onderhoud</html>", b"{}", b'["a"]', b'{"downloadUrl": ""}'):
        c = opbouw.controleer_sleutel(KEY, lambda url, **kw: body)
        assert c.geldig is False and KEY not in c.melding
    assert opbouw.controleer_sleutel("  ", lambda *a, **k: b"{}").geldig is False


def test_the_key_is_kept_only_on_request_and_other_lines_stay(store, tmp_path):
    assert opbouw.bewaarde_sleutel(store) is None
    env = store.root / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("# eigen notitie\nANDERE=1\nEPONLINE_API_KEY=oud\n", encoding="utf-8")
    assert opbouw.bewaarde_sleutel(store) == "oud"
    assert opbouw.bewaar_sleutel(store, f" {KEY}\n") == env
    text = env.read_text(encoding="utf-8")
    assert text.count("EPONLINE_API_KEY") == 1 and "# eigen notitie" in text and "ANDERE=1" in text
    assert opbouw.bewaarde_sleutel(store) == KEY
    opbouw.vergeet_sleutel(store)
    assert opbouw.bewaarde_sleutel(store) is None
    assert env.read_text(encoding="utf-8").splitlines() == ["# eigen notitie", "ANDERE=1"]
    env.write_text(f"EPONLINE_API_KEY={KEY}\n", encoding="utf-8")
    opbouw.vergeet_sleutel(store)
    assert not env.exists()
    assert not (tmp_path / ".env").exists()            # never in the working directory


def test_the_environment_variable_comes_first(store, monkeypatch):
    opbouw.bewaar_sleutel(store, "uit-bestand")
    monkeypatch.setenv(st.EPONLINE_KEY_ENV, "uit-omgeving")
    assert opbouw.bewaarde_sleutel(store) == "uit-omgeving"


# -- route and plan ---------------------------------------------------------------------------

def _t(**kw):
    return Toestand(**{"populatie": False, "populatie_met_labels": False, "pakket_zip": False,
                       "ep_parquet": False, "ep_versie": None, **kw})


def _namen(stappen):
    return [s.naam for s in stappen]


PAKKET = "Datapakket downloaden en controleren"
EP_DL = "EP-online downloaden"
EP_LEES = "EP-online inlezen"
POP = "Populatie en signaturen uitrekenen"


def test_plan_gives_the_steps_each_state_and_source_needs(store, tmp_path):
    ep_bestand = tmp_path / "ep.zip"
    ep_bestand.write_bytes(b"x")
    # nothing there yet
    assert _namen(opbouw.plan(store, _t(), Bron.SLEUTEL, key=KEY)) == [PAKKET, EP_DL, EP_LEES, POP]
    assert _namen(opbouw.plan(store, _t(), Bron.BESTAND, bestand=ep_bestand)) == [
        PAKKET, EP_LEES, POP]
    assert _namen(opbouw.plan(store, _t(), Bron.GEEN)) == [PAKKET, POP]
    # package already downloaded
    assert _namen(opbouw.plan(store, _t(pakket_zip=True), Bron.SLEUTEL, key=KEY)) == [
        EP_DL, EP_LEES, POP]
    assert _namen(opbouw.plan(store, _t(pakket_zip=True), Bron.GEEN)) == [POP]
    # a population without labels: only EP-online is added (the package must be there)
    gemaakt = _t(populatie=True, pakket_zip=True)
    assert _namen(opbouw.plan(store, gemaakt, Bron.SLEUTEL, key=KEY)) == [EP_DL, EP_LEES, POP]
    assert opbouw.plan(store, gemaakt, Bron.GEEN) == []          # nothing to do
    # ... and when the zip was deleted it comes back
    assert _namen(opbouw.plan(store, _t(populatie=True), Bron.BESTAND, bestand=ep_bestand)) == [
        PAKKET, EP_LEES, POP]
    # a package of one's own: no download of it
    assert _namen(opbouw.plan(store, _t(), Bron.GEEN, pakket=tmp_path / "x.zip")) == [POP]


def test_an_ep_download_that_is_there_already_is_skipped_but_shown(store):
    (store.downloads / EP_NAAM).write_bytes(b"x")
    alle = opbouw.overzicht(store, _t(pakket_zip=True), Bron.SLEUTEL, key=KEY, ep_zip=EP_NAAM)
    assert [(s.naam, s.klaar) for s in alle] == [(PAKKET, True), (EP_DL, True), (EP_LEES, False),
                                                 (POP, False)]
    assert _namen(opbouw.plan(store, _t(pakket_zip=True), Bron.SLEUTEL, key=KEY,
                              ep_zip=EP_NAAM)) == [EP_LEES, POP]


def test_plan_refuses_what_cannot_run(store, tmp_path):
    with pytest.raises(ValueError):
        opbouw.plan(store, _t(), Bron.SLEUTEL, key="  ")
    with pytest.raises(ValueError):
        opbouw.plan(store, _t(), Bron.BESTAND, bestand=tmp_path / "bestaat-niet.zip")
    with pytest.raises(ValueError):
        opbouw.plan(store, _t(), Bron.PAKKET, pakket_manifest={"ep_online": "tekst"})
    with pytest.raises(NotImplementedError):               # route A is only recognised
        opbouw.plan(store, _t(), Bron.PAKKET, pakket_manifest={"ep_online": {"in_pakket": True}})


def test_ep_route_reads_the_manifest_and_knows_only_route_a():
    # today's manifest: a text in ep_online
    assert opbouw.ep_route({"ep_online": "niet gebruikt in dit pakket"}) is None
    # the two agreed future shapes
    assert opbouw.ep_route({"ep_online": {"in_pakket": True}}) is Bron.PAKKET
    ep = {"naam": "ep.zip", "manifest": "ep.json", "toegang": "open"}
    assert opbouw.ep_route({"varianten": {"ep": ep}}) is Bron.PAKKET
    # route C (with a key) has no step yet: route B then
    assert opbouw.ep_route({"varianten": {"ep": {**ep, "toegang": "sleutel"}}}) is None
    # nonsense
    for rommel in (None, [], "tekst", {"ep_online": {"in_pakket": "ja"}}, {"varianten": 3},
                   {"varianten": {"ep": "x"}}, {"varianten": {"ep": {"toegang": "open"}}}):
        assert opbouw.ep_route(rommel) is None


def test_the_state_line_and_the_state(wereld, store):
    t = opbouw.toestand(store)
    assert not t.populatie and opbouw.toestand_regel(t) == "Nog geen populatie op deze computer"
    opbouw.voer_uit(wereld.plan(store, Bron.GEEN), lambda f, t: None, klok=Klok())
    t = opbouw.toestand(store)
    assert t.populatie and t.pakket_zip and not t.populatie_met_labels and t.woningen == 600
    regel = opbouw.toestand_regel(t)
    assert regel.startswith("600 woningen, datapakket van ") and regel.endswith(
        "zonder EP-online-labels")
    assert opbouw.aantal_tekst(6_200_000) == "6,2 miljoen"


# -- running ------------------------------------------------------------------------------------

def test_a_run_with_a_key_ends_with_labels_and_one_rising_bar(wereld, store):
    meldingen = []
    opbouw.voer_uit(wereld.plan(store, Bron.SLEUTEL, key=KEY, ep_zip=EP_NAAM),
                    lambda f, t: meldingen.append((f, t)), klok=Klok())
    t = opbouw.toestand(store)
    assert t.populatie_met_labels and t.ep_parquet and "publicatie 01-09-2026" in t.ep_versie
    assert "met EP-online (publicatie 01-09-2026)" in opbouw.toestand_regel(t)
    pop = pd.read_parquet(store.population_path)
    first = pop[pop["vbo_id__str"].isin(wereld.ids)]
    assert (first["energielabel__cat"] == "C").all() and len(first) == 50
    fracties = [f for f, _ in meldingen if f is not None]
    assert fracties == sorted(fracties) and fracties[0] == 0.0 and fracties[-1] == 1.0
    teksten = [t for _, t in meldingen]
    assert any(x.startswith("1 van 4: Datapakket downloaden") and " MB" in x for x in teksten)
    assert any(x.startswith("2 van 4: EP-online downloaden · ") for x in teksten)
    assert any(x.startswith("3 van 4: EP-online inlezen · ") and x.endswith("%") for x in teksten)
    assert any(x.startswith("4 van 4: Populatie") for x in teksten)
    # every step skips what is there: a second run has nothing left to download
    wereld.aanroepen.clear()
    opbouw.voer_uit(wereld.plan(store, Bron.SLEUTEL, key=KEY, ep_zip=EP_NAAM),
                    lambda f, t: None, klok=Klok())
    assert st.DATAPAKKET_URL not in wereld.aanroepen and "https://ep.test/totaal" not in \
        wereld.aanroepen


def test_the_key_is_nowhere_after_a_run(wereld, store):
    meldingen = []
    opbouw.voer_uit(wereld.plan(store, Bron.SLEUTEL, key=f" {KEY} "),
                    lambda f, t: meldingen.append(t), klok=Klok())
    assert meldingen and not any(KEY in t for t in meldingen)
    for pad in (store.root, store.downloads):
        for f in pad.rglob("*"):
            if f.is_file() and f.suffix in {".json", ".env", ".txt", ".csv", ""}:
                assert KEY.encode() not in f.read_bytes(), f
    assert KEY not in store.manifest_path.read_text(encoding="utf-8")


def test_an_error_text_never_holds_the_key(wereld, store):
    def stuk(url, dest, **kw):
        raise RuntimeError(f"verbinding met {url}?key={KEY} verbroken")
    stappen = opbouw.plan(store, _t(pakket_zip=True), Bron.SLEUTEL, key=KEY,
                          fetcher=wereld.fetcher, downloader=stuk)
    with pytest.raises(RuntimeError) as e:
        opbouw.voer_uit(stappen, lambda f, t: None, klok=Klok())
    assert KEY not in str(e.value) and "verbroken" in str(e.value) and e.value.__cause__ is None
    wereld.sleutel_fout = _http(401, f"ongeldig: {KEY}")
    stappen = opbouw.plan(store, _t(pakket_zip=True), Bron.SLEUTEL, key=KEY,
                          fetcher=wereld.fetcher, downloader=wereld.downloader)
    with pytest.raises(RuntimeError) as e:                 # an HTTPError that quotes the key
        opbouw.voer_uit(stappen, lambda f, t: None, klok=Klok())
    assert KEY not in str(e.value) and "ongeldig" in str(e.value)


def test_an_own_totaalbestand_gives_the_same_labels(wereld, store, tmp_path):
    opbouw.voer_uit(wereld.plan(store, Bron.BESTAND, bestand=wereld.ep_zip),
                    lambda f, t: None, klok=Klok())
    assert opbouw.toestand(store).populatie_met_labels
    assert st.EPONLINE_URL not in wereld.aanroepen


def test_cancelling_leaves_the_old_population_and_a_second_run_finishes(wereld, store):
    opbouw.voer_uit(wereld.plan(store, Bron.GEEN), lambda f, t: None, klok=Klok())
    voor = store.population_path.read_bytes()
    stop = threading.Event()

    def melding(f, t):
        if t.startswith("3 van 3"):             # in the last step: stop at its next message
            stop.set()

    stappen = wereld.plan(store, Bron.SLEUTEL, key=KEY, ep_zip=EP_NAAM)
    assert len(stappen) == 3
    with pytest.raises(opbouw.Geannuleerd):
        opbouw.voer_uit(stappen, melding, stop=stop, klok=Klok())
    assert store.population_path.read_bytes() == voor           # never half
    assert not opbouw.toestand(store).populatie_met_labels
    opbouw.voer_uit(wereld.plan(store, Bron.SLEUTEL, key=KEY, ep_zip=EP_NAAM),
                    lambda f, t: None, klok=Klok())
    assert opbouw.toestand(store).populatie_met_labels
    # stopped before the first step
    stop.set()
    with pytest.raises(opbouw.Geannuleerd):
        opbouw.voer_uit(wereld.plan(store, Bron.GEEN) or [opbouw.Stap("x", 1, lambda v: None)],
                        lambda f, t: None, stop=stop)


def test_a_wrong_package_in_downloads_is_removed_before_installing(wereld, store):
    shutil.copy(wereld.pub / "manifest.json", store.downloads / datapakket.MANIFEST_NAME)
    (store.downloads / datapakket.ZIP_NAME).write_bytes(b"kapot")
    stappen = wereld.plan(store, Bron.GEEN)
    assert _namen(stappen) == [POP]
    with pytest.raises(ValueError, match="verwijderd"):
        opbouw.voer_uit(stappen, lambda f, t: None, klok=Klok())
    assert not (store.downloads / datapakket.ZIP_NAME).exists()
    assert not opbouw.toestand(store).pakket_zip           # the next plan downloads it again


def test_the_bar_is_divided_by_the_weights():
    meldingen = []
    stappen = [opbouw.Stap("a", 100, lambda v: None), opbouw.Stap("b", 300, lambda v: v.set(0.5))]
    opbouw.voer_uit(stappen, lambda f, t: meldingen.append(round(f, 3)), klok=Klok())
    assert 0.25 in meldingen and 0.625 in meldingen and meldingen[-1] == 1.0
    leeg = []
    opbouw.voer_uit([opbouw.Stap("a", 0, lambda v: None)], lambda f, t: leeg.append(f))
    assert leeg[-1] == 1.0


def test_space_is_checked_before_the_start(store, monkeypatch):
    manifest = {"zip": {"bytes": 500_000_000}}
    assert opbouw.benodigde_ruimte(manifest) == 3_000_000_000
    assert opbouw.benodigde_ruimte(None) == opbouw.RUIMTE_EXTRA_B
    usage = namedtuple("usage", "total used free")
    free = lambda n: (lambda path: usage(10 * n, 0, n))  # noqa: E731
    monkeypatch.setattr(shutil, "disk_usage", free(5_000_000_000))
    assert opbouw.controleer_ruimte(store, manifest) is None
    monkeypatch.setattr(shutil, "disk_usage", free(1_000_000_000))
    melding = opbouw.controleer_ruimte(store, manifest)
    assert "1,0 GB vrij" in melding and "3,0 GB" in melding


# -- the clock ----------------------------------------------------------------------------------

def test_the_time_texts():
    nu = datetime(2026, 10, 2, 14, 0, 0)
    assert klaar_rond(None, nu) == ""
    assert klaar_rond(35 * 60 + 40, nu) == "klaar rond 14:35"
    assert klaar_rond(59 * 60, datetime(2026, 10, 2, 14, 0, 0)) == "klaar rond 15:00"
    assert klaar_rond(3 * 3600, datetime(2026, 10, 2, 22, 10)) == "klaar rond morgen 01:10"
    stappen = [opbouw.Stap("a", 600, lambda v: None), opbouw.Stap("b", 3600, lambda v: None)]
    assert vooraf_schatting(stappen) == "ongeveer 1 uur 10 minuten (schatting)"
    assert vooraf_schatting(stappen[:1]) == "ongeveer 10 minuten (schatting)"
    assert vooraf_schatting([opbouw.Stap("c", 7200, lambda v: None)]) == \
        "ongeveer 2 uur (schatting)"
    assert vooraf_schatting([]) == ""


def test_the_estimate_follows_steps_of_different_pace():
    """The second step is three times slower than its reference: the estimate is too low after
    the first one and then catches up; it never goes negative and ends at 'bijna klaar'."""
    t = [0.0]
    schatter, reeks = Schatter(), []

    def stap(duur, delen=10):
        def doe(v):
            for i in range(1, delen + 1):
                t[0] += duur / delen
                v.set(i / delen)
        return doe

    def melding(fraction, text):
        if fraction is not None:
            reeks.append((fraction, t[0], schatter.remaining(fraction, t[0])))

    opbouw.voer_uit([opbouw.Stap("a", 100, stap(100)), opbouw.Stap("b", 300, stap(900))], melding,
                    klok=lambda: t[0] + 1000 * len(reeks))                  # never throttled
    assert all(r is None or r >= 0 for _, _, r in reeks)
    na_a = next(r for f, _, r in reeks if f >= 0.25 and r is not None)
    assert na_a == pytest.approx(300, rel=0.05)                  # believes the reference pace
    laat = [(tt, r) for f, tt, r in reeks if f >= 0.9 and r is not None]
    assert abs(laat[0][0] + laat[0][1] - 1000) < 100      # the finishing time (1000 s): close
    assert schatter.text(1.0, t[0]) == "bijna klaar"


# -- the extensions of the existing functions ------------------------------------------------

def test_ingest_eponline_reports_a_fraction_of_the_bytes_read(store, wereld, tmp_path):
    zip_fracties, csv_fracties = [], []
    st.ingest_eponline(store, wereld.ep_zip, fraction=zip_fracties.append)
    assert zip_fracties and zip_fracties[-1] == 1.0 and zip_fracties == sorted(zip_fracties)
    csv = tmp_path / "ep.csv"
    with zipfile.ZipFile(wereld.ep_zip) as z:
        csv.write_bytes(z.read("totaal.csv"))
    st.ingest_eponline(store, csv, fraction=csv_fracties.append)
    assert csv_fracties[-1] == 1.0
    assert len(pd.read_parquet(store.raw / "ep_online.parquet")) == 50


def test_install_reports_a_fraction_of_the_dwellings(wereld, store):
    fracties = []
    datapakket.install(wereld.pkg, store, batch_rows=250, fraction=fracties.append)
    assert fracties == [250 / 600, 500 / 600, 1.0]


def test_eponline_info_is_the_request_the_download_makes(wereld):
    info = st.eponline_info(KEY, wereld.fetcher)
    assert info["bestandsnaam"] == EP_NAAM


def test_download_reports_bytes_after_every_chunk(tmp_path, monkeypatch):
    class Antwoord(io.BytesIO):
        status = 200
        headers = {"Content-Length": "10"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Antwoord(b"0123456789"))
    gezien = []
    st.download("https://x.test/f", tmp_path / "f", on_bytes=lambda d, t: gezien.append((d, t)))
    assert gezien == [(10, 10)] and (tmp_path / "f").read_bytes() == b"0123456789"


def test_the_command_line_uses_the_same_steps_and_never_prints_the_key(wereld, tmp_path,
                                                                        monkeypatch, capsys):
    import argparse

    from anonymate import cli
    monkeypatch.setenv("ANONYMATE_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(st, "fetch", wereld.fetcher)
    monkeypatch.setattr(st, "download", wereld.downloader)
    args = argparse.Namespace(source="pakket", file=None, home=None, downloads=None, jaar=None,
                              max_tegels=None, tegels_weggooien=False)
    cli.cmd_ingest(args)                                    # without a key: with the explanation
    uit = capsys.readouterr().out
    assert opbouw.EP_AANVRAAG_URL in uit and "Populatie en signaturen" in uit
    assert not opbouw.toestand(st.Store.open()).populatie_met_labels
    monkeypatch.setenv(st.EPONLINE_KEY_ENV, KEY)
    cli.cmd_ingest(args)                                    # with a key: EP-online as well
    uit = capsys.readouterr().out
    assert KEY not in uit and "EP-online inlezen" in uit
    assert opbouw.toestand(st.Store.open()).populatie_met_labels
