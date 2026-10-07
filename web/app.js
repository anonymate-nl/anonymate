// De schil van AnonyMate in de browser: de zeven stappen van het Windows-programma. Al het
// rekenwerk gebeurt in worker.js (Pyodide, anonymate.web); hier wordt alleen getoond en doorgegeven.
// De teksten en tekeningen volgen gui.py en gui_tekening.py.
"use strict";

const $ = (s) => document.querySelector(s);
const BASE = new URL(".", location.href).href;
const SVGNS = "http://www.w3.org/2000/svg";
let worker = null;
let nextId = 1;
const pending = new Map();
let isReady = false;    // de rekenkern is opgestart
let markReady, markFailed;
const ready = new Promise((resolve, reject) => { markReady = resolve; markFailed = reject; });
ready.catch(() => {});  // een mislukte start wordt getoond door wie erop wachtte

// ---- de staat van de pagina ----

const STEPS = ["Dataset", "Norm", "Kolommen", "Signatuur", "Weerlocatie", "Aanvaller", "Uitkomst"];
const st = {
  opened: null,       // antwoord van open_*: kolommen, detecties, catalogus, norm, provincies
  example: false,     // het voorbeeldbestand van de oefenmodus
  locked: false,      // de norm is vastgelegd
  locking: false,     // de norm wordt vastgelegd (de knop wacht op de rekenkern)
  p: 0.09,
  k: 11,
  current: 0,         // getoonde stap
  furthest: 0,        // verste stap die bezocht is (voor de vinkjes in de rail)
  busy: false,
  result: null,       // antwoord van run/suggest/apply
  steps: null,        // de generalisatiestappen van suggest
  view: "nut",   // weergave van de afweging: nut | verlies
  doel: 95,           // het doel van de zoektocht, in procent (voor deze sessie)
  chosenStep: -1,
  adopted: false,
  versie: 0,          // telt elke opdracht die iets in de rekenkern verandert (zie call)
  gezocht: null,      // zoekSleutel() van de laatste geslaagde zoektocht
  selectedRow: -1,
  regionText: "heel Nederland",
  wcols: [],          // de weerkolommen die in de dataset zitten (weerzone_h3, weer_knmi_station, uhi)
  uhiFile: null,      // het gekozen UHI-bestand
};

// ---- kleine hulpen ----

const nlf = (x, d = 1) => Number(x).toFixed(d).replace(".", ",");
const nr = (x) => Math.round(Number(x)).toLocaleString("nl-NL");
// Python's round() rondt .5 naar even af; k = round(1/p) moet in beide talen gelijk zijn
function pyRound(x) {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 ? 2 * Math.round(x / 2) : r;
}
function h(tag, props, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  e.append(...kids.filter((x) => x != null));
  return e;
}
function s(tag, props, ...kids) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  e.append(...kids.filter((x) => x != null));
  return e;
}
function fout(text) {
  return h("span", { class: "fout", text });
}
function debounce(fn, ms) {
  let t = null;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
// tekstbreedte voor de tekeningen: een canvas meet, zonder dat er iets zichtbaar wordt
const meter = document.createElement("canvas").getContext("2d");
function breedte(text, px = 11.3) {
  meter.font = `${px}px "Segoe UI", system-ui, sans-serif`;
  return meter.measureText(text).width;
}

// ---- de worker, gestart vanuit een blob:-URL zodat hij de policy van deze pagina erft ----

async function startWorker() {
  const src = await (await fetch("worker.js")).text();
  const url = URL.createObjectURL(new Blob([src], { type: "text/javascript" }));
  worker = new Worker(url);
  worker.onmessage = (e) => {
    const m = e.data;
    if (m.type === "status") return loadText(m.text, m.fase);
    if (m.type === "progress") {
      const p = pending.get(m.id);
      if (p && p.voortgang) p.voortgang.update(m.fraction, m.text);
      return;
    }
    if (m.type === "achtergrond") return toonAchtergrond(m);
    const p = pending.get(m.id);
    pending.delete(m.id);
    if (!p) return;
    if (m.ok) p.resolve(m.result);
    else { const err = new Error(m.error); err.technical = m.technical; p.reject(err); }
  };
}

// Alles behalve "start" wacht tot de rekenkern klaar is: wie eerder klikt, staat in de rij.
// `voortgang` (zie maakVoortgang): de balk die de voortgangsberichten van deze aanroep laat zien.
// Opdrachten die niets in de rekenkern veranderen; elke andere (ook een onbekende of mislukte)
// telt als wijziging, zodat "Generalisaties zoeken" daarna weer kan.
// De teller gaat omhoog bij het versturen, zodat een trage opdracht die al liep niet midden in een
// zoektocht meetelt.
const ALLEEN_LEZEN = new Set(["background", "norm", "run", "suggest", "target_text", "record", "export",
  "set_region", "uhi_bron", "trace_open", "trace", "forget_eponline", "map_cell", "map_cells", "map_hit", "map_layers",
  "map_station"]);
async function call(cmd, args = {}, transfer = [], voortgang = null) {
  if (cmd !== "start") await ready;
  const wijzigt = !ALLEEN_LEZEN.has(cmd);
  if (wijzigt) st.versie++;
  const t0 = performance.now();
  const klaar = (gelukt) => {
    const sec = (performance.now() - t0) / 1000;
    if (sec >= 0.5) registreerTijd(cmd, sec, gelukt);
    if (wijzigt) busyButtons();
  };
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve: (v) => { klaar(true); resolve(v); },
                      reject: (e) => { klaar(false); reject(e); }, voortgang });
    worker.postMessage({ id, cmd, args }, transfer);
  });
}

// ---- de gedeelde voortgangsbalk ----
// Eén component voor elke lange aanroep: een balk (gevuld naar de fractie, of onbepaald zolang die
// niet bekend is) in een omlijst vak van vaste breedte: op de eerste regel de tekst, op de tweede de
// balk met rechts (vaste plek) "nog ongeveer m:ss", elke seconde ververst. Alleen de tijd die nog te
// gaan is, nooit de verstreken tijd; zonder fractie blijft die plek leeg.
// De rekenkern meldt alleen fractie en tekst (anonymate.voortgang); de tijd rekent de pagina.
const clock = (sec) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
const ETA_VANAF = 0.05;
const BIJNA_KLAAR = 3.0;
const GLADDEN = 0.3;
// PORT van anonymate.voortgang.Schatter (Python, ook in het Windows-programma): houd ze gelijk.
function resttekst(rest) {
  if (rest == null) return "schatting volgt…";
  if (rest < BIJNA_KLAAR) return "bijna klaar";
  const stap = rest < 60 ? 5 : 10;
  return `nog ongeveer ${clock(Math.max(Math.round(rest / stap) * stap, stap))}`;
}
class Schatter {
  constructor() { this.einde = null; }         // gladgestreken moment van klaar zijn (in seconden)
  tekst(fraction, elapsed) {
    if (fraction == null) return "";
    if (fraction > ETA_VANAF) {
      const ruw = elapsed + elapsed * (1 - fraction) / fraction;
      this.einde = this.einde == null ? ruw : GLADDEN * ruw + (1 - GLADDEN) * this.einde;
    }
    return resttekst(this.einde == null ? null : Math.max(this.einde - elapsed, 0));
  }
}
function maakVoortgang(host) {
  const vulling = h("div");
  const balk = h("div", { class: "balk onbepaald" }, vulling);
  const tekst = h("div", { class: "vg-tekst" });
  const tijdtekst = h("span", { class: "vg-tijd" });
  host.classList.add("voortgang");
  host.replaceChildren(tekst, h("div", { class: "vg-rij" }, balk, tijdtekst));
  host.hidden = true;
  let t0 = 0, fractie = null, label = "", klok = null, schatter = new Schatter();
  const toon = () => {
    const tijd = schatter.tekst(fractie, (performance.now() - t0) / 1000);
    tekst.textContent = label || "aan het rekenen";
    tekst.title = tekst.textContent;                   // de hele tekst, als hij is afgekapt
    tijdtekst.textContent = tijd;
  };
  const v = {
    actief: false,
    start(text = "aan het rekenen") {
      t0 = performance.now(); fractie = null; schatter = new Schatter(); label = text; v.actief = true;
      balk.classList.add("onbepaald"); vulling.style.width = "0%";
      host.hidden = false; toon();
      clearInterval(klok); klok = setInterval(toon, 1000);
    },
    // voortgang van de berekening; zonder fractie (onbekend) blijft de balk onbepaald
    update(fraction, text) {
      if (!v.actief) return;
      if (text) label = text;
      if (fraction != null) {
        fractie = Math.max(fractie || 0, fraction);        // nooit terug
        balk.classList.remove("onbepaald");
        vulling.style.width = Math.round(100 * fractie) + "%";
      }
      toon();
    },
    stop() { v.actief = false; clearInterval(klok); host.hidden = true; },
  };
  return v;
}
// een lange aanroep met zijn balk: aan bij het begin, uit als hij klaar is (ook bij een fout)
async function metVoortgang(v, text, cmd, args, transfer) {
  v.start(text);
  try { return await call(cmd, args, transfer || [], v); } finally { v.stop(); }
}

// ---- tijden meten: ?tijden=1 toont elke lange stap met zijn duur, om te kopiëren ----
// Alleen voor wie meet (web/proef.ps1); de tijden blijven in de pagina.
window.__tijden = [];
const STAPNAAM = { start: "rekenkern opstarten", open_population: "populatie openen", add_eponline: "EP-online toevoegen", use_eponline: "bewaarde labels laden",
  open_file: "dataset openen", open_practice: "oefenen openen", run: "toetsen",
  suggest: "generalisaties zoeken", apply: "generalisatie toepassen", weather: "weerlocatie",
  trace: "weerspoor", map_cell: "kaartcel", export: "uitkomst maken", background: "achtergrond laden" };
function registreerTijd(cmd, sec, gelukt) {
  const regel = { tijdstip: new Date().toLocaleTimeString("nl-NL"), stap: cmd,
                  wat: STAPNAAM[cmd] || "", seconden: Math.round(sec * 10) / 10, gelukt };
  window.__tijden.push(regel);
  console.log("tijd: " + JSON.stringify(regel));
  if (new URLSearchParams(location.search).has("tijden")) tekenTijden();
}
function tekenTijden() {
  let vak = document.getElementById("tijden-vak");   // maakt de pagina zelf, staat niet in index.html
  if (!vak) {
    vak = h("div", { id: "tijden-vak" });
    vak.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:99;max-width:420px;" +
      "background:var(--card);border:1px solid var(--line);border-radius:8px;padding:8px 10px;" +
      "font:12px/1.4 var(--mono);box-shadow:0 2px 8px rgba(0,0,0,.15)";
    document.body.append(vak);
    // verslepen aan de kop, zodat het vak geen knop van de pagina afdekt
    vak.addEventListener("pointerdown", (e) => {
      if (!e.target.closest(".tijden-kop") || e.target.closest("button")) return;
      const r = vak.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
      const beweeg = (m) => {
        vak.style.left = Math.max(0, Math.min(innerWidth - 40, m.clientX - dx)) + "px";
        vak.style.top = Math.max(0, Math.min(innerHeight - 20, m.clientY - dy)) + "px";
        vak.style.right = vak.style.bottom = "auto";
      };
      const los = () => { removeEventListener("pointermove", beweeg); removeEventListener("pointerup", los); };
      addEventListener("pointermove", beweeg);
      addEventListener("pointerup", los);
      e.preventDefault();
    });
  }
  const tekst = () => window.__tijden.map((r) =>
    `${r.tijdstip}  ${r.stap.padEnd(14)} ${String(r.seconden).padStart(7)} s${r.gelukt ? "" : "  (fout)"}  ${r.wat}`).join("\n");
  const knop = h("button", { class: "knop", type: "button" }, "Tijden kopiëren");
  knop.onclick = () => navigator.clipboard.writeText(navigator.userAgent + "\n" + tekst())
    .then(() => { knop.textContent = "Gekopieerd"; });
  const pre = h("pre", {}, tekst());
  pre.style.cssText = "margin:0 0 6px;white-space:pre-wrap";
  // inklappen tot alleen de kop; de stand blijft bij een nieuwe meting
  const dicht = vak.dataset.dicht === "1";
  const klap = h("button", { type: "button", title: dicht ? "Uitklappen" : "Inklappen" }, dicht ? "+" : "−");
  klap.style.cssText = "float:right;margin-left:8px;padding:0 6px;cursor:pointer";
  klap.onclick = () => { vak.dataset.dicht = dicht ? "0" : "1"; tekenTijden(); };
  const kop = h("div", { class: "tijden-kop", title: "Versleep het vak aan deze kop" },
    klap, h("strong", {}, `Tijden (${window.__tijden.length})`));
  kop.style.cssText = "cursor:move;user-select:none;margin-bottom:" + (dicht ? "0" : "4px");
  vak.replaceChildren(kop, ...(dicht ? [] : [pre, knop]));
}
const vgHoofd = maakVoortgang($("#voortgang")); // toetsen, generalisaties, overnemen
const vgKaart = maakVoortgang($("#kaart-bezig"));                 // een cel op de kaart uitrekenen
const vgSpoor = maakVoortgang($("#t-voortgang"));                 // het weerspoor
const vgWeer = maakVoortgang($("#w-voortgang"));                  // weerlocatie en UHI toevoegen
const vgOpen = maakVoortgang($("#open-voortgang"));               // een dataset openen

// ---- opstarten ----

// Het opstarten heeft vaste fasen (de tijden die de worker meet, zie worker.js) en er is nog geen
// Python om een fractie te melden. Dus schat de pagina zelf: per fase een verwachte duur, eerst de
// standaardwaarden (gemeten op een laptop), daarna de echte tijden van het vorige bezoek (in
// localStorage). Nog te gaan = de verwachte duur van de fasen die nog komen + wat er van de huidige
// fase over is; hij telt elke halve seconde af en wordt bij elke fase opnieuw geschat.
// Staat de pagina onder de service worker, dan komen Python en de pakketten uit de cache van deze
// browser, niet van de server; zeg dat dan ook
const UIT_BROWSER = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
const FASEN = [
  { sleutel: "python_pakketten", standaard: 14,
    tekst: UIT_BROWSER ? "Python en rekenbibliotheken laden uit deze browser"
      : "Python en rekenbibliotheken downloaden (eenmalig ongeveer 20 MB)" },
  { sleutel: "wheel", standaard: 0.1, tekst: "AnonyMate starten", stap: 2 },
  { sleutel: "import", standaard: 6, tekst: "AnonyMate starten", stap: 2 },
];
const TIJDEN_SLEUTEL = "anonymate.opstarttijden";
const MAX_FASE = 120;                       // een fase die (ooit) langer duurde dan dit, geloven we niet
function verwachteDuren() {
  let vorige = {};
  try { vorige = JSON.parse(localStorage.getItem(TIJDEN_SLEUTEL) || "{}") || {}; } catch (_) { /* geen opslag */ }
  return FASEN.map((f) => {
    const t = vorige[f.sleutel];
    return typeof t === "number" && isFinite(t) && t > 0 && t < MAX_FASE ? t : f.standaard;
  });
}
function bewaarTijden(timings) {
  try {
    const uit = {};
    FASEN.forEach((f) => {
      const t = timings && timings[f.sleutel];
      if (typeof t === "number" && isFinite(t) && t > 0 && t < MAX_FASE) uit[f.sleutel] = t;
    });
    localStorage.setItem(TIJDEN_SLEUTEL, JSON.stringify(uit));
  } catch (_) { /* geen opslag: dan de standaardwaarden */ }
}
// wat de opstartbalk toont, uit de duren, de huidige fase en de tijd die die al loopt
function opstartToestand(duren, fase, inFase) {
  const totaal = duren.reduce((a, b) => a + b, 0);
  const voor = duren.slice(0, fase).reduce((a, b) => a + b, 0);
  const rest = duren.slice(fase + 1).reduce((a, b) => a + b, 0) + Math.max(duren[fase] - inFase, 0);
  const klaar = voor + Math.min(inFase, duren[fase]);
  return { rest, fractie: Math.min(0.95, klaar / totaal) };
}

let loadPhase = 0, loadStart = 0, loadPhaseStart = 0, loadDuren = [], loadClock = null;
function showLoad() {
  const nu = performance.now();
  const f = FASEN[loadPhase];
  const { rest, fractie } = opstartToestand(loadDuren, loadPhase, (nu - loadPhaseStart) / 1000);
  // uitpakken (~0,1 s) en starten tonen we als één stap: anders springt de teller van 1 naar 3
  const stappen = Math.max(...FASEN.map((x, i) => x.stap || i + 1));
  const tekst = `stap ${f.stap || loadPhase + 1} van ${stappen}: ${f.tekst}… · ${resttekst(rest)}`;
  if ($("#laadtekst").textContent !== tekst) $("#laadtekst").textContent = tekst;
  $("#laadbalk").style.width = Math.round(100 * fractie) + "%";
}
function startLoad() {
  loadDuren = verwachteDuren();
  loadPhase = 0;
  loadStart = loadPhaseStart = performance.now();
  showLoad();
  loadClock = setInterval(showLoad, 500);
}
// een bericht van de worker: bij een nieuwe fase telt de schatting daar opnieuw vanaf
function loadText(text, fase) {
  const i = FASEN.findIndex((f) => f.sleutel === fase);
  if (i > loadPhase && loadClock) {
    loadPhase = i;
    loadPhaseStart = performance.now();
    showLoad();
  }
}

// versie en commit uit manifest.json (het bestand waar de attestatie over gaat)
async function toonBron() {
  try {
    const m = await (await fetch(new URL("manifest.json", BASE), { cache: "no-cache" })).json();
    $("#bronversie").textContent = m.anonymate;
    const c = m.bron && m.bron.commit;
    if (c && /^[0-9a-f]{40}$/.test(c)) {
      const a = $("#broncommit");
      a.textContent = c.slice(0, 7);
      a.href = m.bron.repo + "/commit/" + c;
      a.title = c;
    } else {
      $("#broncommit").textContent = "onbekend";
    }
  } catch (err) {
    $("#bron").hidden = true;
  }
}

async function boot() {
  const csp = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
  $("#csp").textContent = csp ? csp.content : "";
  toonBron();
  showOnline();
  buildStatic();
  st.view = weergaveBewaard();
  go(0);      // stap 1 staat er meteen; de rekenkern laadt ondertussen
  startLoad();
  try {
    await startWorker();
    const v = await call("start", { base: BASE });
    isReady = true;
    clearInterval(loadClock);
    markReady();
    $("#laadbalk").style.width = "100%";
    $("#laadtekst").textContent =
      `Klaar: Python ${v.python}, Pyodide ${v.pyodide}, AnonyMate ${v.anonymate}.`;
    window.__timings = v.timings;
    bewaarTijden(v.timings);
    console.log("opstarten (s): " + JSON.stringify(v.timings));
    setTimeout(() => { $("#laden").hidden = true; }, 600);
    startAchtergrond();
    proefPopulatie();
  } catch (err) {
    clearInterval(loadClock);
    markFailed(err);
    $("#laadtekst").replaceChildren(fout("Opstarten mislukt: " + err.message));
  }
}

// ---- proef fase 3: ?populatie=<pad> opent een echte populatie van dezelfde herkomst ----
async function proefPopulatie() {
  const pad = new URLSearchParams(location.search).get("populatie");
  if (!pad) return;
  console.log("proef fase 3: populatie " + pad + " openen…");
  try {
    const t0 = performance.now();
    const out = await call("open_population", { url: pad, base: BASE });
    window.__populatie = out;
    console.log("proef fase 3: " + JSON.stringify(out) + ", totaal " +
                Math.round(performance.now() - t0) / 1000 + " s");
    toonEpKaart(out);
  } catch (err) {
    console.log("proef fase 3 mislukt: " + err.message);
  }
}

// ---- fase 4: EP-online uit het eigen totaalbestand (route 4) ----
// De kaart staat er zodra er een echte populatie open is. Het bestand gaat als File naar de worker,
// die het alleen-lezen koppelt; de pagina leest het zelf niet in.
const vgEp = maakVoortgang($("#ep-voortgang"));
function toonEpKaart(populatie) {
  $("#ep-kaart").hidden = !!populatie.labels;     // met labels valt er niets toe te voegen
  const b = populatie.bewaard;                    // eerder gekoppeld en in deze browser bewaard
  $("#ep-bewaard").hidden = !b;
  if (!b) return;
  if (b.month && b.month === dezeMaand()) {        // nog actueel: meteen gebruiken
    gebruikBewaard();
    return;
  }
  $("#ep-gebruik").hidden = false;
  $("#ep-gebruik").textContent = `Labels van ${maandNaam(b.month)} gebruiken`;
  $("#ep-melding").textContent = `Bewaard in deze browser: de labels van ${maandNaam(b.month)}. ` +
    "Er is inmiddels een nieuwer totaalbestand; koppel dat, of gebruik de bewaarde labels.";
}
const dezeMaand = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
};
const maandNaam = (m) => (m ? new Date(m + "-01T12:00").toLocaleDateString("nl-NL",
  { month: "long", year: "numeric" }) : "een onbekende maand");

// de labels gelden nu: een uitkomst tegen de populatie zonder labels niet meer
function naLabels(melding) {
  epKlaar();
  $("#ep-gebruik").hidden = true;
  if (st.result) {
    st.result = null;
    st.steps = null;
    clearOutcome();
    melding.textContent += " Toets je dataset opnieuw.";
  }
}
async function gebruikBewaard() {
  const melding = $("#ep-melding");
  $("#ep-kies").disabled = $("#ep-gebruik").disabled = true;
  melding.textContent = "bewaarde labels laden…";
  try {
    const o = await metVoortgang(vgEp, "bewaarde EP-online-labels laden", "use_eponline", {});
    melding.textContent = `Uit deze browser: ${nlGetal(o.labels)} van de ${nlGetal(o.population)} ` +
      `woningen hebben een label (${o.version}).`;
    naLabels(melding);
  } catch (err) {
    melding.replaceChildren(fout(err.message + " Koppel het totaalbestand opnieuw."));
    $("#ep-kies").disabled = false;
  } finally {
    $("#ep-gebruik").disabled = false;
  }
}
$("#ep-gebruik").onclick = gebruikBewaard;
$("#ep-wis").onclick = async () => {
  await call("forget_eponline");
  $("#ep-bewaard").hidden = true;
  $("#ep-melding").textContent += " De bewaarde labels zijn uit deze browser gewist" +
    ($("#ep-kies").disabled ? " (deze sessie gebruikt ze nog)." : ".");
};
function epKlaar() {
  $("#ep-sleep").hidden = true;
  $("#ep-stappen").hidden = true;
  $("#ep-kies").disabled = true;
}
async function voegEpToe(file) {
  if (!file) return;
  const melding = $("#ep-melding");
  if (!/\.(zip|csv)$/i.test(file.name)) {
    melding.replaceChildren(fout(`${file.name}: kies de zip van het totaalbestand (of de csv daaruit).`));
    return;
  }
  $("#ep-kies").disabled = true;
  melding.textContent = `${file.name} koppelen…`;
  try {
    const t0 = performance.now();
    const o = await metVoortgang(vgEp, `EP-online lezen: ${file.name}`, "add_eponline", { file });
    const sec = Math.round(performance.now() - t0) / 1000;
    console.log("fase 4: " + JSON.stringify(o) + ", totaal " + sec + " s");
    window.__eponline = { ...o, totaal: sec };
    melding.textContent = `Toegevoegd: ${nlGetal(o.labels)} van de ${nlGetal(o.population)} ` +
      `woningen hebben een label (${o.version}). Duur: ${klokTijd(sec)}.`;
    if (o.bewaard) {
      melding.textContent += " Bewaard in deze browser: in dezelfde maand hoeft dit niet opnieuw.";
      $("#ep-bewaard").hidden = false;
      // vraag de browser de opslag niet op te ruimen als de schijf vol raakt
      if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
    } else if (o.bewaarfout) {
      melding.textContent += ` (Niet bewaard in deze browser: ${o.bewaarfout})`;
    }
    naLabels(melding);
  } catch (err) {
    melding.replaceChildren(fout(err.message));
    $("#ep-kies").disabled = false;
  }
}
const nlGetal = (n) => Number(n).toLocaleString("nl-NL");
const klokTijd = (sec) => (sec < 60 ? `${Math.round(sec)} s` : `${clock(sec)} min`);
$("#ep-kies").onclick = () => $("#ep-bestand").click();
$("#ep-bestand").onchange = (e) => { voegEpToe(e.target.files[0]); e.target.value = ""; };
const epDrop = $("#ep-sleep");
epDrop.ondragover = (e) => { e.preventDefault(); epDrop.classList.add("over"); };
epDrop.ondragleave = () => epDrop.classList.remove("over");
epDrop.ondrop = (e) => {
  e.preventDefault();
  epDrop.classList.remove("over");
  voegEpToe(e.dataTransfer.files[0]);
};

// ---- de rest op de achtergrond laden ----
// Na het opstarten is het programma bruikbaar; wat latere stappen nodig hebben (h3, de Python-modules
// van kaart en weerspoor) komt daarna binnen, in een eigen berichtenketen naast de aanroepen van
// de gebruiker. "Alles is geladen" staat er pas als ook dat binnen is.
let alleGeladen = false;      // alles op de achtergrond is binnen
let offlineKlaar = false;     // de service worker heeft alle bestanden in zijn cache

// "Offline beschikbaar" alleen als beide waar zijn; anders (geen service worker) blijft het oude
// "Alles is geladen" staan
function toonOffline() {
  $("#offlineklaar").hidden = !(alleGeladen && offlineKlaar);
  $("#klaaroffline").hidden = !alleGeladen || offlineKlaar;
}

// ---- de service worker: offline na het eerste bezoek ----
// Pas registreren als het programma is opgestart, zodat het binnenhalen van ruim 25 MB in de cache
// het eerste gebruik niet ophoudt. Waar service workers ontbreken (of een fout geven), werkt de
// pagina gewoon door, alleen niet offline. Een nieuwe versie neemt de pagina niet zelf over midden
// in een beoordeling: de gebruiker herlaadt zelf.
async function startOffline() {
  if (!("serviceWorker" in navigator)) return;
  try {
    const sw = navigator.serviceWorker;
    sw.addEventListener("message", (e) => {
      if (e.data && e.data.type === "offline") { offlineKlaar = !!e.data.klaar; toonOffline(); }
    });
    const reg = await sw.register("sw.js");
    const nieuw = (w) => w.addEventListener("statechange", () => {
      if (w.state === "installed" && sw.controller) toonNieuweVersie(reg.waiting || w);
    });
    if (reg.waiting && sw.controller) toonNieuweVersie(reg.waiting);
    reg.addEventListener("updatefound", () => reg.installing && nieuw(reg.installing));
    // de actieve versie weet of alles binnen is
    const actief = (await sw.ready).active;
    const kanaal = new MessageChannel();
    kanaal.port1.onmessage = (e) => { offlineKlaar = !!(e.data && e.data.klaar); toonOffline(); };
    if (actief) actief.postMessage({ type: "status" }, [kanaal.port2]);
  } catch (err) {
    console.warn("service worker niet beschikbaar:", err && err.message);
  }
}

function toonNieuweVersie(wachtend) {
  $("#nieuweversie").hidden = false;
  $("#herlaad").onclick = () => {
    navigator.serviceWorker.addEventListener("controllerchange", () => location.reload());
    wachtend.postMessage({ type: "overnemen" });
  };
}

const ACHTERGROND_NAAM = { h3: "het pakket h3", modules: "de modules voor kaart en weerspoor" };

function toonAchtergrond(m) {
  const wacht = Object.keys(m.staat).filter((n) => m.staat[n] !== "klaar");
  const mislukt = wacht.filter((n) => m.staat[n] === "mislukt");
  const alles = wacht.length === 0;
  alleGeladen = alles;
  toonOffline();
  const box = $("#achtergrond");
  box.hidden = alles;
  if (alles) { box.textContent = ""; return; }
  const namen = (l) => l.map((n) => ACHTERGROND_NAAM[n] || n).join(", ");
  box.textContent = mislukt.length
    ? `Laden op de achtergrond is niet gelukt voor ${namen(mislukt)}; het wordt opnieuw geprobeerd ` +
      "zodra een stap het nodig heeft."
    : `De rest wordt op de achtergrond geladen… nog te laden: ${namen(wacht)}.`;
}

function startAchtergrond() {
  const box = $("#achtergrond");
  box.hidden = false;
  box.textContent = "De rest wordt op de achtergrond geladen…";
  // pas op een rustig moment, zodat de eerste klikken van de gebruiker voorgaan
  const start = async () => {
    try {
      const r = await call("background");
      const t = { ...(window.__timings || {}), ...r.timings };
      window.__timings = t;
      console.log("opstarten (s): " + JSON.stringify(t));
      if (Object.keys(r.fouten).length) console.warn("laden op de achtergrond:", JSON.stringify(r.fouten));
    } catch (err) {
      console.warn("laden op de achtergrond mislukt:", err && err.message);
    }
    startOffline();
  };
  if (window.requestIdleCallback) requestIdleCallback(start, { timeout: 1500 });
  else setTimeout(start, 300);
}

function showOnline() {
  const on = navigator.onLine;
  $("#online").textContent = on ? "online" : "offline: de toets werkt gewoon door";
  $("#dot").classList.toggle("uit", !on);
}
addEventListener("online", showOnline);
addEventListener("offline", showOnline);

// ---- de rail en de navigatie ----

function go(n) {
  // voorbij de norm alleen met een vastgelegde norm (zoals gui._row_changed)
  if (n >= 2 && !st.locked) n = st.opened ? 1 : 0;
  st.current = n;
  if (st.opened) st.furthest = Math.max(st.furthest, n);
  document.querySelectorAll("[data-paneel]").forEach((el) => {
    el.hidden = Number(el.dataset.paneel) !== n;
  });
  window.scrollTo(0, 0);
  refreshRail();
  if (n === 4) enterWeather();
  if (n === 6) { redrawBits(); toonDoel(); }
}

function mapping() {
  const m = {};
  document.querySelectorAll("#kolommen select").forEach((sel) => { m[sel.dataset.column] = sel.value; });
  return m;
}

function scenarioText() {
  const o = $("#scenario").selectedOptions[0];
  return o ? o.textContent.split(" (")[0] : "";
}

// zoals gui._refresh_rail: ondertitels, en het vinkje (✓) van wat af is
function refreshRail() {
  const has = !!st.opened;
  const m = has ? Object.values(mapping()) : [];
  const nQid = m.filter((v) => v !== "geen" && v !== "direct").length;
  const nDirect = m.filter((v) => v === "direct").length;
  const subs = [
    has ? st.opened.name : "nog niet gekozen",
    `p ${nlf(st.p, 2)} · k ≥ ${st.k}` + (st.locked ? " · vast" : ""),
    has ? `${nQid} kenmerken, ${nDirect} weglaten` : "",
    $("#sig-aan").checked ? "aan" : "niet gebruikt",
    weatherSub(),
    scenarioText(),
    st.result ? `${st.result.summary.ok} van ${st.result.summary.records} publiceerbaar`
              : "nog niet getoetst",
  ];
  const passed = (i) => has && st.furthest > i;
  const assessed = !!st.result;
  const done = [has, st.locked, passed(2), passed(3), passed(4), passed(5) || assessed, assessed];
  const rail = $("#rail");
  STEPS.forEach((name, i) => {
    const li = rail.children[i];
    li.classList.toggle("nu", i === st.current);
    li.classList.toggle("klaar", done[i]);
    li.querySelector("b").textContent = `${done[i] ? `${i + 1} ✓` : `${i + 1}  `}  ${name}`;
    li.querySelector("span").textContent = subs[i];
    // voorbij stap 2 pas als de norm vastligt
    li.querySelector("button").disabled = (i > 0 && !has) || (i > 1 && !st.locked);
    if (i === st.current) li.querySelector("button").setAttribute("aria-current", "step");
    else li.querySelector("button").removeAttribute("aria-current");
  });
  const card = $("#datasetkaart");
  if (!has) { card.textContent = "nog geen dataset"; return; }
  card.replaceChildren(h("b", { text: st.opened.name }), h("br"),
    `${st.opened.records} woningen · ${st.opened.columns.length} kolommen`, h("br"),
    `regio: ${st.regionText}`,
    ...(st.locked ? [h("br"), `norm p = ${nlf(st.p, 2)} · k ≥ ${st.k}`] : []));
}

// ---- statische onderdelen: rail, regio, signatuur, ijkpunten ----

function buildStatic() {
  const rail = $("#rail");
  STEPS.forEach((name, i) => {
    const b = h("button", { type: "button" }, h("b"), h("span"));
    b.onclick = () => go(i);
    rail.append(h("li", { "data-stap": i }, b));
  });
  // regio: twaalf provincies (de lijst komt met de eerste dataset uit de facade; tot dan de vaste)
  buildProvinces(["Drenthe", "Flevoland", "Fryslân", "Gelderland", "Groningen", "Limburg",
    "Noord-Brabant", "Noord-Holland", "Overijssel", "Utrecht", "Zeeland", "Zuid-Holland"]);
  // afrondstappen van de signatuur
  const SIG = [["H", "H", "W/K", 50, 1000, "warmteverlies per graad verschil tussen binnen en buiten"],
    ["C", "C", "Wh/K", 5000, 100000, "warmtecapaciteit: hoeveel warmte de woning vasthoudt"],
    ["tau", "τ", "h", 0, 500, "tijdconstante C/H: hoe snel de woning afkoelt"],
    ["Asol", "A_sol", "m²", 0, 200, "effectief zonoppervlak: hoeveel zonnewarmte binnenkomt"],
    ["Ainf", "A_inf", "cm²", 0, 1000, "infiltratie-apertuur: hoeveel lucht door kieren naar binnen lekt"]];
  for (const [key, sym, unit, def, top, meaning] of SIG) {
    const inp = h("input", { type: "number", min: 0, max: top, step: 1, value: def,
      id: `sig-${key}`, title: `${meaning}; afrondstap in ${unit}, 0 = niet publiceren`,
      "aria-label": `afrondstap ${sym} in ${unit}` });
    $("#sig-stappen").append(h("span", { title: meaning, text: sym }), inp, h("span", { class: "melding", text: unit }));
  }
  $("#sig-legenda").replaceChildren(
    SIG.slice(0, 2).map(([, sym, , , , m]) => `${sym}: ${m}`).join(" · "), h("br"),
    SIG.slice(2).map(([, sym, , , , m]) => `${sym}: ${m}`).join(" · "));
  // de norm: de schuif en het getal lopen gelijk
  $("#p-schuif").oninput = (e) => setP(Number(e.target.value) / 100);
  $("#p").oninput = (e) => { if (e.target.value !== "") setP(Number(e.target.value)); };
  $("#p").onchange = (e) => setP(Number(e.target.value) || st.p);
  setP(0.09);
  $("#lock").onclick = lockAndContinue;
  $("#naar-norm").onclick = () => go(1);
  $("#naar-signatuur").onclick = () => go(3);
  $("#naar-aanvaller-a").onclick = () => go(4);
  $("#naar-aanvaller-w").onclick = () => go(5);
  $("#sig-aan").onchange = refreshRail;
  $("#scenario").onchange = refreshRail;
  $("#toets").onclick = runAssess;
  $("#zoek").onclick = runSuggest;
  $("#verken").onclick = runExplore;
  $("#overnemen").onclick = adopt;
  $("#opslaan").onclick = save;
  $("#stoppen").onclick = stopPractice;
  document.querySelectorAll(".tab").forEach((t, i) => {
    t.onclick = () => showTab(i);
    t.onkeydown = (e) => {
      const to = e.key === "ArrowRight" ? (i + 1) % 3 : e.key === "ArrowLeft" ? (i + 2) % 3 : null;
      if (to != null) { showTab(to); $(`#tab-${to}`).focus(); }
    };
  });
  addEventListener("resize", debounce(redrawBits, 150));
  setNormMarks(null);
  renderSignature();
  buildWeather();
}

function buildProvinces(names) {
  const box = $("#provincies");
  box.replaceChildren();
  for (const n of names) {
    const c = h("input", { type: "checkbox", disabled: "", "data-provincie": n });
    c.onchange = () => sendRegion().catch(() => {});
    box.append(h("label", { class: "vinkje" }, c, n));
  }
}
function regionState() {
  return {
    heel: $("#regio-heel").checked,
    provincies: [...document.querySelectorAll("[data-provincie]")].filter((c) => c.checked)
      .map((c) => c.dataset.provincie),
    gemeenten: $("#regio-gemeenten").value,
  };
}
async function sendRegion() {
  const state = regionState();
  const r = await call("set_region", state);
  st.regionText = r.text;
  const key = JSON.stringify(state);
  if (kaart.regionKey !== null && kaart.regionKey !== key) {     // andere regio: andere kaart
    invalidateMap();
    if (st.current === 4) ensureMap();
  }
  kaart.regionKey = key;
  refreshRail();
}
$("#regio-heel").onchange = () => {
  const heel = $("#regio-heel").checked;
  document.querySelectorAll("[data-provincie]").forEach((c) => { c.disabled = heel; });
  $("#regio-gemeenten").disabled = heel;
  sendRegion().catch(() => {});
};
$("#regio-gemeenten").onchange = () => sendRegion().catch(() => {});

// ---- stap 1: dataset ----

function busyButtons() {
  const ready = !!st.opened && st.locked && !st.busy;
  $("#toets").disabled = !ready;
  const gezocht = st.gezocht !== null && st.gezocht === zoekSleutel();
  $("#zoek").disabled = !ready || gezocht;
  $("#zoek").title = gezocht ? "Al gezocht met deze instellingen; wijzig iets om opnieuw te zoeken" : "";
  $("#verken").disabled = !ready;
  $("#opslaan").disabled = !st.result || st.busy;
  $("#overnemen").disabled = st.busy || !st.steps || st.steps.length < 2 || st.adopted;
  $("#kies").disabled = st.busy;
  $("#oefen").disabled = st.busy;
  $("#naar-norm").disabled = !st.opened;
  $("#lock").disabled = !st.opened || st.locking;
  $("#toets-hint").hidden = !st.opened || st.locked;
}

async function openPractice() {
  const b = $("#oefen");
  const text = b.textContent;
  try {
    if (!isReady) {
      b.disabled = true;
      $("#dataset-melding").textContent = "wacht op de rekenkern…";
      await ready;
    }
    b.disabled = true;
    b.textContent = "Oefenpopulatie openen…";
    const o = await metVoortgang(vgOpen, "oefenpopulatie openen", "open_practice", {});
    console.log("opstarten (s): " + JSON.stringify(o.timings));
    await loadDataset(o, true);
  } catch (err) {
    $("#dataset-melding").replaceChildren(fout(err.message));
  } finally {
    b.textContent = text;
    busyButtons();
  }
}
$("#oefen").onclick = openPractice;

async function openFile(file) {
  if (!file) return;
  const melding = $("#dataset-melding");
  melding.textContent = `${file.name} lezen…`;
  try {
    const data = await file.arrayBuffer();
    if (!isReady) {
      melding.textContent = `${file.name}: wacht op de rekenkern…`;
      await ready;
      melding.textContent = `${file.name} lezen…`;
    }
    await loadDataset(await metVoortgang(vgOpen, `${file.name} lezen`, "open_file",
      { name: file.name, data }, [data]), false);
  } catch (err) {
    melding.replaceChildren(fout(err.message));
  }
}
$("#kies").onclick = () => $("#bestand").click();
$("#bestand").onchange = (e) => { openFile(e.target.files[0]); e.target.value = ""; };
const drop = $("#sleep");
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  openFile(e.dataTransfer.files[0]);
};

// zoals gui.MainWindow.load: alles terug naar af, de kolommen voorgeselecteerd, en naar de norm
async function loadDataset(o, example) {
  st.opened = o;
  toonDoel();
  st.example = example;
  st.result = null;
  st.steps = null;
  st.locked = false;
  st.furthest = 0;
  st.adopted = false;
  clearOutcome();
  $("#foutmelding").hidden = true;
  $("#dataset-melding").textContent = `${o.name}: ${o.records} records, ${o.columns.length} kolommen`;
  const noot = $("#dataset-noot");
  noot.hidden = example || !o.practice;
  noot.textContent = "Let op: de echte populatie volgt in een latere versie. Tot dan toets je ook " +
    "een eigen bestand tegen het verzonnen Nederland van de oefenmodus: de uitkomst zegt niets " +
    "over echte woningen.";
  if (!o.practice) console.log("tegen de echte populatie: " + o.population + " woningen");
  $("#oefenbalk").hidden = !o.practice;
  regionRestore();
  st.regionText = o.region || "heel Nederland";
  buildColumns(o);
  $("#koppel").value = (o.link_columns || []).join(",");
  initWeather(o, example);
  renderSignature();
  setNormMarks(o.norm);
  setP(o.norm ? o.norm.default : 0.09);
  $("#p").disabled = false;
  $("#p-schuif").disabled = false;
  $("#lock").textContent = LOCK_TEXT;
  $("#lock-tekst").textContent = "nog niet vastgelegd: toetsen kan pas daarna";
  busyButtons();
  go(1);
}
// de provincies zijn opnieuw opgebouwd: het vinkje "heel Nederland" bepaalt of ze aan mogen
function regionRestore() {
  const heel = $("#regio-heel").checked;
  document.querySelectorAll("[data-provincie]").forEach((c) => { c.disabled = heel; });
}

async function stopPractice() {
  try { await call("stop_practice"); } catch (err) { /* de pagina zelf gaat toch terug */ }
  st.opened = null;
  st.result = null;
  st.steps = null;
  st.locked = false;
  st.furthest = 0;
  clearOutcome();
  $("#oefenbalk").hidden = true;
  $("#dataset-noot").hidden = true;
  $("#dataset-melding").textContent = "Oefenmodus gestopt. Open nu je eigen dataset.";
  $("#kolommen").replaceChildren();
  resetWeather();
  busyButtons();
  go(0);
}

// ---- stap 3: kolommen ----

function buildColumns(o) {
  const t = $("#kolommen");
  t.replaceChildren();
  t.append(h("thead", {}, h("tr", {}, ...["kolom", "voorstel", "behandelen als", "reden"]
    .map((x) => h("th", { text: x })))));
  const body = h("tbody");
  for (const d of o.detections) body.append(columnRow(d, o.catalogue));
  t.append(body);
}
// één rij van de kolommentabel; ook de weerkolommen van stap 5 komen hier
function columnRow(d, catalogue) {
  const sel = h("select", { "data-column": d.column, "aria-label": `rol van ${d.column}` });
  sel.add(new Option("(geen)", "geen"));
  sel.add(new Option("(weglaten)", "direct"));
  for (const [k, label] of Object.entries(catalogue || {})) {
    const opt = new Option(k, k);
    opt.title = label;
    sel.add(opt);
  }
  sel.value = d.default;             // voorgeselecteerd zoals het Windows-programma
  sel.onchange = refreshRail;
  return h("tr", { "data-kolom": d.column },
    h("td", { text: d.column }), h("td", { text: d.proposal }), h("td", {}, sel),
    h("td", { class: "reden", text: d.reason || "" }));
}

// ---- stap 4: signatuur (in de oefenmodus uitgeschakeld) ----

function renderSignature() {
  const practice = !!(st.opened && st.opened.practice);
  $("#sig-uit").hidden = !practice;
  const off = practice;
  if (off) $("#sig-aan").checked = false;
  $("#sig-aan").disabled = off;
  $("#sig-aan").title = off ? "Niet in de oefenmodus: het verzonnen Nederland heeft geen signaturen." : "";
  for (const el of [$("#koppel"), $("#sig-methode"), ...document.querySelectorAll("#sig-stappen input")]) {
    el.disabled = off;
  }
  refreshRail();
}

// ---- stap 2: norm ----

function setNormMarks(norm) {
  const marks = norm ? norm.marks : [
    { p: 0.05, k: 20, text: "streng: openbare publicatie van gevoelige gegevens" },
    { p: 0.09, k: 11, text: "standaard van AnonyMate" },
    { p: 0.10, k: 10, text: "netbeheerders, verbruik per PC6" },
    { p: 0.20, k: 5, text: "medisch, gecontroleerde toegang" },
    { p: 0.33, k: 3, text: "ondergrens, gecontroleerde toegang" }];
  $("#markeringen").replaceChildren(...marks.map((m) =>
    h("div", {}, h("b", { text: `${nlf(m.p, 2)} · k ≥ ${m.k}` }), h("br"), m.text)));
}

// dezelfde tekst als anonymate.web.norm; de rekenkern bevestigt hem zodra die klaar is
function localNorm(p) {
  const k = pyRound(1 / p);
  const filled = Math.min(k, 20);
  return { p, k, big: `k ≥ ${k}`, houses: [filled, filled, 0],
    text: `Elke woning in de dataset moet lijken op minstens ${k} woningen in de populatie: wie er ` +
      `één zoekt, heeft hooguit 1 op ${k} kans. Van zo'n groep mag hooguit ${Math.round(p * 100)}% ` +
      "in de dataset zitten (anders verraadt de groep dat een woning meedoet: deelnameonthulling)." };
}
function renderNorm(n) {
  st.k = n.k;
  $("#k-groot").textContent = n.big;
  $("#k-tekst").textContent = n.text;
  $("#norm-huizen").replaceChildren(houseSvg(n.houses[0], n.houses[1], n.houses[2], 30));
  refreshRail();
}
let normToken = 0;
function setP(p) {
  if (st.locked) return;
  p = Math.min(0.33, Math.max(0.05, Math.round(p * 100) / 100));
  st.p = p;
  $("#p-schuif").value = String(Math.round(p * 100));
  if (document.activeElement !== $("#p")) $("#p").value = p.toFixed(2);
  renderNorm(localNorm(p));
  const token = ++normToken;
  if (isReady) {
    call("norm", { p }).then((n) => { if (token === normToken && !st.locked) renderNorm(n); })
      .catch(() => {});
  }
}

// dezelfde teksten als het Windows-programma (gui.LOCK_TEXT en LOCKED_TEXT)
const LOCK_TEXT = "Norm vastleggen en verder";
const LOCKED_TEXT = "Norm vastgelegd · verder";

// één knop: legt de norm vast (één keer) en gaat naar stap 3; de enige weg voorbij stap 2
async function lockAndContinue() {
  if (!st.opened) return;
  if (!st.locked) {
    st.locking = true;
    busyButtons();
    try {
      const n = await call("lock_norm", { p: st.p });
      st.locked = true;
      st.p = n.p;
      st.k = n.k;
      $("#p").disabled = true;
      $("#p-schuif").disabled = true;
      $("#lock").textContent = LOCKED_TEXT;
      $("#lock-tekst").textContent = n.label;
      renderNorm(n);
    } catch (err) {
      $("#lock-tekst").replaceChildren(fout(err.message));
      return;
    } finally {
      st.locking = false;
      busyButtons();
    }
  }
  go(2);
}

// ---- de tekeningen: huisjes, bitsbalk, k-histogram, afweging (SVG, zoals gui_tekening.py) ----

// k huisjes uit k plaatsen: de eerste is de woning in kwestie (oranje), de rest wat er nog bij hoort;
// gestippeld wat nog ontbreekt tot de norm. "+n" als er meer zijn dan er getekend worden.
function houseSvg(filled, total, more, size) {
  const step = size + 6;
  const n = total + (more ? 2 : 0);
  const svg = s("svg", { class: "tekening", viewBox: `0 0 ${Math.max(n, 1) * step} ${size + 4}`,
    width: Math.max(n, 1) * step, height: size + 4, role: "img",
    "aria-label": `${filled} van ${total} huizen${more ? `, en nog ${more}` : ""}` });
  const sz = size;
  const path = `M${.12 * sz},${.46 * sz} L${.5 * sz},${.14 * sz} L${.88 * sz},${.46 * sz} ` +
    `L${.88 * sz},${.86 * sz} L${.12 * sz},${.86 * sz} Z`;
  for (let i = 0; i < total; i++) {
    const g = s("g", { transform: `translate(${i * step},2)` });
    if (i < filled) {
      const target = i === 0;
      g.append(s("path", { d: path, fill: target ? "var(--orange)" : "var(--blue-soft)",
        stroke: target ? "var(--orange-ink)" : "var(--huis-lijn)", "stroke-width": 1.4 }));
    } else {
      g.append(s("path", { d: path, fill: "none", stroke: "var(--leeg)", "stroke-width": 1.2,
        "stroke-dasharray": "4 3" }));
    }
    svg.append(g);
  }
  if (more) {
    svg.append(s("text", { x: total * step, y: size / 2 + 6, class: "stil",
      "font-family": "Consolas, monospace", "font-size": 13, text: `+${nr(more)}` }));
  }
  return svg;
}

// Guess Who: de bits die elk kenmerk prijsgeeft, wat er nog te gaan is, en de norm als streep
function redrawBits() {
  const box = $("#bits");
  box.replaceChildren();
  const b = st.result && st.result.bits;
  if (!b || b.needed <= 0) return;
  const W = Math.max(box.clientWidth || 300, 260);
  const w = W - 8;
  const parts = b.parts;
  const rest = b.remaining_median;                  // null: onbekend (geen enkel record heeft een match)
  const total = Math.max(b.needed, parts.reduce((a, p) => a + p.median, 0) + (rest || 0));
  const scale = w / total;
  const [y, hh] = [8, 24];
  const svg = s("svg", { class: "tekening", width: W, height: 92, viewBox: `0 0 ${W} 92`, role: "img" });
  const tip = [...parts.map((p) => `${p.column}: ${nlf(p.median)} bits`),
    rest == null ? "nog te gaan: onbekend (geen enkel record heeft een match)"
      : `nog te gaan: ${nlf(rest)} bits`,
    `norm: minstens ${nlf(b.norm_bits)} te gaan`].join("\n");
  svg.append(s("title", { text: tip }));
  let x = 4;
  const rowEnd = [-1e9, -1e9];
  let skipped = 0;
  parts.forEach((p, i) => {
    const width = p.median * scale;
    svg.append(s("rect", { x, y, width: Math.max(width, 0), height: hh, fill: `var(--bit${i % 6})` }));
    const text = `${p.column} ${nlf(p.median)}`;
    const tw = breedte(text);
    const lx = Math.min(x, w + 4 - tw);
    const row = [0, 1].find((r) => lx >= rowEnd[r] + 6);
    if (row === undefined) skipped += 1;
    else {
      svg.append(s("text", { x: lx, y: y + hh + 2 + 15 * row + 12, "font-size": 11.3, text }));
      rowEnd[row] = lx + tw;
    }
    x += width;
  });
  if (rest != null) {
    const rw = rest * scale;
    svg.append(s("rect", { x, y, width: Math.max(rw, 0), height: hh, fill: "var(--rest)",
      stroke: "var(--rest-rand)" }));
    let text = `nog te gaan: ${nlf(rest)}`;
    if (breedte(text) + 10 > rw) text = nlf(rest);
    if (breedte(text) + 8 <= rw) {
      svg.append(s("text", { x: x + 6, y: y + hh / 2 + 4, "font-size": 11.3, text }));
    }
  }
  const nx = 4 + (total - b.norm_bits) * scale;
  svg.append(s("line", { x1: nx, y1: 2, x2: nx, y2: y + hh + 6, stroke: "var(--orange-ink)",
    "stroke-width": 2 }));
  let norm = `norm: minstens ${nlf(b.norm_bits)} te gaan`;
  if (skipped) norm += " · wijs aan voor alles";
  const tw = breedte(norm);
  svg.append(s("text", { x: Math.max(4, Math.min(nx + 4, w + 4 - tw)), y: y + hh + 34 + 12,
    "font-size": 11.3, text: norm }));
  box.append(svg);
}

const short = (n) => (n >= 1000 ? `${+(n / 1000).toPrecision(6)}k` : `${n}`);

// hoeveel woningen hoeveel gelijke woningen hebben, in klassen, met de norm als streep
function drawHistogram(bins, normK) {
  const box = $("#histogram");
  box.replaceChildren();
  if (!bins.length) return;
  const [w, hgt] = [230, 150];
  const svg = s("svg", { class: "tekening", width: w, height: hgt, viewBox: `0 0 ${w} ${hgt}`,
    role: "img", "aria-label": "aantal woningen per klasse van gelijke woningen" });
  const n = bins.length;
  const bw = (w - 10) / n;
  const [top, base] = [30, hgt - 22];          // ruimte boven de hoogste staaf voor "k = …"
  const peak = Math.max(...bins.map((b) => b.n), 1);
  bins.forEach((b, i) => {
    const bh = (base - top) * b.n / peak;
    const rx = 5 + i * bw + 4;
    svg.append(s("rect", { x: rx, y: base - bh, width: Math.max(bw - 8, 1), height: bh,
      fill: i === 0 ? "var(--risico-rand)" : "var(--blue)" }));
    svg.append(s("text", { x: rx + (bw - 8) / 2, y: base - bh - 4, "text-anchor": "middle",
      "font-size": 10.7, text: String(b.n) }));
    const open = b.hi == null;
    let label = i === 0 ? `<${normK}` : (open ? `>${short(b.lo - 1)}` : `${short(b.lo)}–${short(b.hi)}`);
    if (breedte(label, 10.7) > bw - 2 && i > 0 && !open) label = `≥${short(b.lo)}`;
    svg.append(s("text", { x: 5 + i * bw + bw / 2, y: base + 4 + 11, "text-anchor": "middle",
      "font-size": 10.7, class: "stil", text: label }));
  });
  svg.append(s("line", { x1: 5 + bw, y1: top - 12, x2: 5 + bw, y2: base, stroke: "var(--orange-ink)",
    "stroke-width": 1.5, "stroke-dasharray": "5 4" }));
  svg.append(s("text", { x: 5 + bw + 4, y: 11, "font-size": 10.7, text: `k = ${normK}` }));
  box.append(svg);
}

// De afweging in twee weergaven (stappen.TRADEOFF_VIEWS): "nut", naar El Emam & Arbuckle (2013),
// datanut tegen het aandeel woningen dat de norm haalt, en "verlies": informatieverlies tegen
// publiceerbaar. De punten en de teksten komen van de rekenkern (stappen.tradeoff_points).
// target: {pct, label, note} uit de facade, de lijn waar de zoektocht stopt
const WEERGAVE_SLEUTEL = "anonymate.afweging.weergave";
const WEERGAVEN = ["nut", "verlies"];
function weergaveBewaard() {
  try {
    const v = localStorage.getItem(WEERGAVE_SLEUTEL);
    if (WEERGAVEN.includes(v)) return v;
  } catch (_) { /* geen opslag */ }
  return "nut";
}
function drawTradeoff(rows, selected, target = { pct: 95, label: "", note: "" }, tradeoff = null,
  view = st.view) {
  const targetPct = target.pct;
  const box = $("#afweging");
  box.replaceChildren();
  if (!rows.length || !tradeoff) return;
  const texts = tradeoff.views[view];
  const nut = view === "nut";
  const raw = texts.points;
  const [w, hgt] = [720, 330];
  const [left, right, top, bottom] = [58, w - 16, 18, hgt - 34];
  const svg = s("svg", { class: "tekening", width: w, height: hgt, viewBox: `0 0 ${w} ${hgt}`,
    role: "img", style: "width:100%" });
  svg.append(s("title", { text: "Informatieverlies: gemiddeld over woningen en kenmerken. 0% = alle " +
    "waarden exact, 100% = alle kenmerken weggelaten. Een klasse van 10 jaar bij bouwjaren van " +
    "1900 tot 2020 kost bijvoorbeeld zo'n 8%.\n\n" + target.note }));
  let topX = 100, tick = 25;                 // nut: de as staat vast, van geen tot maximaal nut
  if (!nut) {                                // verlies: tot een rond getal net boven het grootste verlies
    const hi = Math.max(...raw.map((q) => q[0]));
    tick = [1, 2, 5, 10, 20, 25].find((t) => hi / t <= 5) || 25;
    topX = Math.max(tick, Math.ceil(hi / tick) * tick);
  }
  const span = right - left - 40;
  const px = (x) => left + x / topX * span;
  const py = (y) => bottom - y / 100 * (bottom - top);
  const ty = py(targetPct);
  const stil = { class: "stil", "font-size": 11.3 };
  // de as en zijn teksten (onder en links van het vlak) zijn ook obstakels voor de labels
  const placed = [{ l: 0, t: bottom + 2, r: w, b: hgt }, { l: 0, t: 0, r: left, b: hgt }];
  if (nut) {                                 // de ideale hoek: veel nut, veel bescherming
    const x0 = px(tradeoff.ideal_from), x1 = px(100);
    const defs = s("defs");
    defs.append(s("pattern", { id: "ideaal-arcering", width: 6, height: 6, patternUnits: "userSpaceOnUse",
      patternTransform: "rotate(45)" }, ));
    defs.firstChild.append(s("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "var(--ideaal)", "stroke-width": 1.2 }));
    svg.append(defs);
    if (ty > top) {
      svg.append(s("rect", { x: x0, y: top, width: x1 - x0, height: ty - top, fill: "var(--ideaal)",
        "fill-opacity": 0.12 }));
      svg.append(s("rect", { x: x0, y: top, width: x1 - x0, height: ty - top, fill: "url(#ideaal-arcering)",
        opacity: 0.55 }));
    }
    const iw = breedte(texts.ideal) + 2;
    svg.append(s("text", { x: x1, y: top - 5, "text-anchor": "end", "font-size": 11.3,
      fill: "var(--ideaal)", text: texts.ideal }));
    placed.push({ l: x1 - iw, t: top - 16, r: x1, b: top - 2 });
  }
  const aslijn = { stroke: "var(--as)", "stroke-width": 1 };
  svg.append(s("line", { x1: left, y1: bottom, x2: right, y2: bottom, ...aslijn }));
  svg.append(s("line", { x1: left, y1: top, x2: left, y2: bottom, ...aslijn }));
  svg.append(s("text", { x: left - 6, y: top - 6 + 11, "text-anchor": "end", ...stil, text: texts.y_max }));
  svg.append(s("text", { x: left - 6, y: bottom - 8 + 11, "text-anchor": "end", ...stil, text: texts.y_min }));
  svg.append(s("text", { transform: `translate(12,${(top + bottom) / 2}) rotate(-90)`,
    "text-anchor": "middle", ...stil, text: texts.y_title }));
  for (let v = 0; v <= topX; v += tick) {
    const x = px(v);
    svg.append(s("line", { x1: x, y1: bottom, x2: x, y2: bottom + 4, ...aslijn }));
    const label = nut && v === 0 ? texts.x_min : nut && v === 100 ? texts.x_max : `${v}%`;
    if (v || nut) svg.append(s("text", { x, y: bottom + 5 + 11, "text-anchor": "middle", ...stil, text: label }));
  }
  svg.append(s("text", { x: right, y: bottom + 18 + 11, "text-anchor": "end", ...stil, text: texts.x_title }));
  if (texts.source) svg.append(s("text", { x: left, y: bottom + 18 + 11, ...stil, text: texts.source }));
  svg.append(s("line", { x1: left, y1: ty, x2: right, y2: ty, stroke: "var(--orange-ink)",
    "stroke-width": 1.2, "stroke-dasharray": "5 4" }));
  const pts = raw.map(([x, y]) => ({ x: px(x), y: py(y) }));
  svg.append(s("polyline", { points: pts.map((q) => `${q.x},${q.y}`).join(" "), fill: "none",
    stroke: "var(--blue)", "stroke-width": 2.2, "stroke-linejoin": "round" }));
  // de punten zelf zijn ook obstakels: een label komt nooit op een punt te liggen
  placed.push(...pts.map((q) => ({ l: q.x - 8, t: q.y - 8, r: q.x + 8, b: q.y + 8 })));
  // wat de oranje stippellijn is: het doel van de zoektocht (links, boven de lijn)
  if (target.label) {
    const gw = breedte(target.label) + 2;
    svg.append(s("text", { x: left + 6, y: ty - 15 + 11, "font-size": 11.3,
      fill: "var(--orange-ink)", text: target.label }));
    placed.push({ l: left + 6, t: ty - 15, r: left + 6 + gw, b: ty - 1 });
  }
  const hit = (a, b) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b;
  const place = (i) => {
    const q = pts[i];
    const text = `${rows[i].label} · ${Math.round(rows[i].pct)}%`;
    const tw = breedte(text) + 2;
    const cands = [
      { l: q.x + 10, t: q.y - 8 }, { l: q.x - 10 - tw, t: q.y - 8 },
      { l: q.x - tw / 2, t: q.y + 8 }, { l: q.x - tw / 2, t: q.y - 24 }];
    for (const c of cands) {
      const rect = { l: c.l, t: c.t, r: c.l + tw, b: c.t + 16 };
      if (rect.l >= 2 && rect.r <= w - 2 && rect.b <= hgt && !placed.some((o) => hit(rect, o))) {
        placed.push(rect);
        svg.append(s("text", { x: rect.l, y: rect.t + 12, "font-size": 11.3, text }));
        return;
      }
    }
  };
  pts.forEach((q, i) => {
    const last = i === selected;
    const r = last ? 7 : 5;
    svg.append(s("circle", { cx: q.x, cy: q.y, r, fill: last ? "var(--orange)" : "var(--blue)",
      stroke: last ? "var(--orange-ink)" : "var(--blue)", "stroke-width": 1.5 }));
  });
  // eerst de gekozen stap, dan de andere waar plaats is (de lijst toont alles)
  if (selected >= 0 && selected < pts.length) place(selected);
  pts.forEach((_, i) => { if (i !== selected) place(i); });
  box.append(svg);
}

// de wisselaar boven de grafiek: twee knoppen, de keuze blijft bewaard
function bouwWissel(tradeoff) {
  $("#afweging-wissel").replaceChildren(...WEERGAVEN.map((v) => {
    const b = h("button", { type: "button", "aria-pressed": String(v === st.view),
      text: tradeoff.views[v].toggle });
    b.onclick = () => {
      st.view = v;
      try { localStorage.setItem(WEERGAVE_SLEUTEL, v); } catch (_) { /* geen opslag */ }
      bouwWissel(tradeoff);
      drawTradeoff(st.steps, st.chosenStep, st.target, st.tradeoff);
    };
    return b;
  }));
}

// ---- stap 7: uitkomst ----

const STATUS = { ok: "publiceerbaar", risico: "te herleidbaar", geen_match: "geen match" };

function showTab(i) {
  document.querySelectorAll(".tab").forEach((t, j) => t.setAttribute("aria-selected", String(i === j)));
  [0, 1, 2].forEach((j) => { $(`#tabvak-${j}`).hidden = j !== i; });
}

// een waarde die niet bekend is, is "–" (grijs, met de reden als tooltip), nooit 0
const ONBEKEND = "–";
const TIP_ONBEKEND = "niet bekend";
const TIP_GEEN_MATCH = "geen match: geen enkele woning in de populatie past hierop, dus dit is niet te bepalen";
function tegel(label, value, tip = "") {
  const onbekend = value === ONBEKEND;
  return h("div", { class: "tegel", title: tip }, h("span", { text: label }),
    h("b", { class: onbekend ? "onbekend" : "", text: value }));
}

function clearOutcome() {
  $("#uitkomst-kop").textContent = "Nog niet getoetst";
  $("#tegels").replaceChildren();
  $("#bits").replaceChildren();
  $("#bits-tekst").textContent = "";
  $("#histogram").replaceChildren();
  $("#histogram-noot").textContent = "";
  $("#woningen").replaceChildren();
  $("#woningen-noot").hidden = true;
  $("#woning-titel").textContent = "Kies een woning in de tabel";
  $("#woning-huizen").replaceChildren();
  $("#woning-tekst").textContent = "";
  $("#woning-kaart").classList.remove("risico");
  $("#toelichting").textContent = "";
  clearSteps();
}
function clearSteps() {
  st.steps = null;
  st.chosenStep = -1;
  $("#afweging").replaceChildren();
  $("#afweging-lijst").replaceChildren();
  $("#afweging-verlies").textContent = "";
}

// zoals gui._show_assessment
function showAssessment(r) {
  st.result = r;
  $("#foutmelding").hidden = true;
  $("#uitkomst-kop").textContent = r.title;
  const tips = r.stats_tips || {};
  $("#tegels").replaceChildren(
    tegel("publiceerbaar", r.stats.ok, tips.ok), tegel("niet publiceren", r.stats.risk, tips.risk),
    tegel("gelijke woningen, mediaan", r.stats.k, tips.k),
    tegel("nog te raden, mediaan", r.stats.bits, tips.bits));
  $("#histogram-noot").textContent = r.histogram_note || "";
  $("#bits-tekst").textContent = r.bits ? r.bits.note : "";
  redrawBits();
  drawHistogram(r.histogram, r.threshold.k);
  $("#toelichting").textContent = r.toelichting.join("\n");
  renderTable(r.table);
  refreshRail();
  showTab(0);
  busyButtons();
}

const MAX_ROWS = 5000;
function renderTable(t) {
  const table = $("#woningen");
  table.replaceChildren();
  st.selectedRow = -1;
  // getallenkolommen rechts, kop erbij; de facade bepaalt welke (stappen.numeric_column)
  const num = (j) => (t.numeric && t.numeric[j] ? "num" : null);
  const kopTip = (c) => (t.column_tips && t.column_tips[c]) || "";
  table.append(h("thead", {}, h("tr", {}, ...t.columns.map((c, j) =>
    h("th", { class: num(j), text: c, title: kopTip(c) })))));
  const body = h("tbody");
  const n = Math.min(t.rows.length, MAX_ROWS);
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) {
    const tr = h("tr", { class: t.status[i], "data-i": i, tabindex: -1 });
    t.rows[i].forEach((v, j) => {
      const nul = v === ONBEKEND;
      const tip = !nul ? "" : (t.status[i] === "geen_match" && (t.columns[j] === "k" || t.columns[j] === "delta")
        ? TIP_GEEN_MATCH : TIP_ONBEKEND);
      tr.append(h("td", { class: [num(j), nul ? "onbekend" : ""].filter(Boolean).join(" "), title: tip, text: v }));
    });
    frag.append(tr);
  }
  body.append(frag);
  table.append(body);
  body.onclick = (e) => {
    const tr = e.target.closest("tr");
    if (tr) selectRow(Number(tr.dataset.i));
  };
  table.tabIndex = 0;
  table.onkeydown = (e) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    selectRow(Math.min(n - 1, Math.max(0, st.selectedRow + (e.key === "ArrowDown" ? 1 : -1))));
  };
  const noot = $("#woningen-noot");
  noot.hidden = t.rows.length <= MAX_ROWS;
  noot.textContent = `De eerste ${nr(MAX_ROWS)} van ${nr(t.rows.length)} regels; alle regels zitten in de zip.`;
  if (t.selected != null) selectRow(t.selected);
}

let recordToken = 0;
async function selectRow(i) {
  st.selectedRow = i;
  document.querySelectorAll("#woningen tbody tr.gekozen").forEach((tr) => tr.classList.remove("gekozen"));
  const tr = document.querySelector(`#woningen tbody tr[data-i="${i}"]`);
  if (tr) { tr.classList.add("gekozen"); tr.scrollIntoView({ block: "nearest" }); }
  const token = ++recordToken;
  try {
    const c = await call("record", { index: i });
    if (token !== recordToken) return;
    $("#woning-titel").textContent = c.title;
    $("#woning-huizen").replaceChildren(houseSvg(c.houses[0], c.houses[1], c.houses[2], 22));
    $("#woning-tekst").textContent = c.text;
    $("#woning-kaart").classList.toggle("risico", c.status !== "ok");
  } catch (err) {
    if (token === recordToken) $("#woning-tekst").replaceChildren(fout(err.message));
  }
}

// ---- toetsen, generalisaties zoeken, overnemen, opslaan ----

function setBusy(on) {
  st.busy = on;
  if (on) {
    $("#toelichting").textContent = "bezig…";
    $("#uitkomst-kop").textContent = "Bezig met toetsen…";
    vgHoofd.start("aan het rekenen");
  } else {
    vgHoofd.stop();
  }
  busyButtons();
}

function failed(err) {
  const message = typeof err === "string" ? err : err.message;
  $("#toelichting").textContent = message +
    (err.technical && err.technical !== message ? "\n\n(technisch: " + err.technical + ")" : "");
  $("#uitkomst-kop").textContent = "Er ging iets mis";
  const box = $("#foutmelding");
  box.textContent = message;
  box.hidden = false;
  go(6);
}

function inputs() {
  return { mapping: mapping(), scenario: $("#scenario").value, scope: $("#afbakening").value };
}

async function runAssess() {
  if (!st.locked) return failed("Leg eerst de privacynorm vast (stap 2).");
  go(6);
  clearSteps();
  st.adopted = false;
  st.gezocht = null;                // de gevonden stappen zijn weg: opnieuw zoeken mag
  setBusy(true);
  try {
    await sendRegion();
    showAssessment(await call("run", inputs(), [], vgHoofd));
  } catch (err) {
    failed(err);
  } finally {
    setBusy(false);
  }
}

// het doel van de zoektocht: 50 tot 100 procent, en wat dat voor deze dataset betekent
function doelWaarde() {
  const v = Math.round(Number($("#doel").value));
  return Number.isFinite(v) ? Math.min(100, Math.max(50, v)) : st.doel;
}
async function toonDoel() {
  st.doel = doelWaarde();
  if (!st.opened) { $("#doel-tekst").textContent = ""; return; }
  try {
    const t = await call("target_text", { share: st.doel / 100 });
    if (st.doel === doelWaarde()) $("#doel-tekst").textContent = t;
  } catch (_) { /* de tekst is bijzaak */ }
}
$("#doel").oninput = debounce(toonDoel, 200);
$("#doel").onchange = () => { $("#doel").value = doelWaarde(); toonDoel(); };

// alles waar de zoektocht van afhangt: na een zoektocht blijft de knop uit tot hier iets verandert
function zoekSleutel() {
  return JSON.stringify({ versie: st.versie, ...inputs(), doel: doelWaarde(), regio: regionState() });
}
// elke wijziging in een keuzelijst, vinkje of veld kan de knop weer aanzetten
document.addEventListener("input", () => busyButtons());
document.addEventListener("change", () => busyButtons());

async function runSuggest() {
  if (!st.locked) return failed("Leg eerst de privacynorm vast (stap 2).");
  go(6);
  setBusy(true);
  try {
    await sendRegion();
    const sleutel = zoekSleutel();
    const r = await call("suggest", { ...inputs(), share: st.doel / 100 }, [], vgHoofd);
    showAssessment(r);
    showSuggestion(r);
    st.gezocht = sleutel;
  } catch (err) {
    failed(err);
  } finally {
    setBusy(false);
  }
}

// zoals gui._show_suggestion: de lijst, de grafiek, en de laatste stap gekozen
function showSuggestion(r) {
  st.steps = r.steps;
  st.adopted = false;
  st.chosenStep = r.selected_step;
  st.target = r.target;
  st.tradeoff = r.tradeoff;
  bouwWissel(r.tradeoff);
  $("#afweging-noot").textContent = r.target ? r.target.note : "";
  $("#afweging-verlies").textContent = r.target ? r.target.loss_note : "";
  const list = $("#afweging-lijst");
  list.replaceChildren(...r.steps.map((step, i) => {
    const b = h("button", { type: "button", text: step.text });
    b.onclick = () => chooseStep(i);
    return h("li", { "data-i": i }, b);
  }));
  chooseStep(r.selected_step);
  showTab(1);
  busyButtons();
}
function chooseStep(i) {
  st.chosenStep = i;
  document.querySelectorAll("#afweging-lijst li").forEach((li) => {
    li.classList.toggle("gekozen", Number(li.dataset.i) === i);
  });
  drawTradeoff(st.steps, i, st.target, st.tradeoff);
}

function runExplore() {
  if (!st.locked) return failed("Leg eerst de privacynorm vast (stap 2).");
  // afronding verkennen gaat over de signatuur, en die is er in de oefenmodus niet
  go(6);
  $("#toelichting").textContent = "Afronding verkennen gaat over de adresgebaseerde signatuur: zet " +
    "stap 4 aan.";
  showTab(2);
}

// "Overnemen": stap i toepassen, zonder de lijst in te korten (zoals gui.adopt)
async function adopt() {
  if (!st.steps) return;
  if (st.chosenStep <= 0) return failed("Kies in de lijst een stap na de uitgangssituatie.");
  setBusy(true);
  try {
    const r = await call("apply", { step: st.chosenStep }, [], vgHoofd);
    for (const c of r.adopted.columns) {
      const sel = document.querySelector(`#kolommen select[data-column="${CSS.escape(c)}"]`);
      if (sel) sel.value = r.mapping[c];
      const cell = document.querySelector(`#kolommen tr[data-kolom="${CSS.escape(c)}"] td.reden`);
      if (cell) cell.textContent = r.adopted.reason;
    }
    st.adopted = true;
    showAssessment(r);
  } catch (err) {
    failed(err);
  } finally {
    setBusy(false);
  }
}

// ---- opslaan: een Blob in dit venster, niets gaat naar een server ----

async function save() {
  const b = $("#opslaan");
  b.disabled = true;
  b.textContent = "Rapport maken…";
  st.busy = true;                   // toetsen en zoeken wachten: ze delen de voortgangsbalk
  busyButtons();
  vgHoofd.start("rapport maken");
  try {
    const bytes = await call("export", {}, [], vgHoofd);
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = (st.opened ? st.opened.name.replace(/\.[^.]+$/, "") : "dataset") + "_anonymate.zip";
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (err) {
    failed(err);
  } finally {
    vgHoofd.stop();
    st.busy = false;
    b.textContent = "Opslaan (zip)";
    busyButtons();
  }
}

// ---- stap 5: weerlocatie, de kaart (canvas) en het weerspoor ----
// De kaart volgt gui_kaart.py (MapWidget): dezelfde lagen, kleuren en bediening. Python rekent de
// H3-grenzen uit (h3.cell_to_boundary) en stuurt ringen van [lengte, breedte]; hier wordt alleen getekend.

// gemiddelde rand (km) en oppervlakte (km²) per H3-niveau: de tabel van h3 (tests/test_web_weer.py
// vergelijkt ze met de bibliotheek)
const H3_EDGE = { 4: 26.07175968, 5: 9.85409099, 6: 3.724532667, 7: 1.406475763, 8: 0.53141401 };
const H3_AREA = { 4: 1770.347654491307, 5: 252.9038581819449, 6: 36.12906216441245,
  7: 5.161293359717191, 8: 0.7373275975944177 };
const KLEUR = { ink: "#172233", muted: "#4A5568", navy: "#1F3A5F", oranje: "#9A4A12",
  achtergrond: "#E8EEF3", cel: "#E4DFD5" };

const kaart = {
  layers: null, geo: null, loading: null, msg: "",
  regionKey: JSON.stringify({ heel: true, provincies: [], gemeenten: "" }),
  mode: "none", level: 5, sigma: 10,
  cells: null, cellsToken: 0,
  selected: null, selLevel: null, sel: null, heat: [], token: 0,
  zoom: 1, panX: 0, panY: 0, drag: null, moved: false, w: 0, h: 0, dpr: 1,
};
const traceState = { info: null, busy: false, started: 0 };

const clamp = (x, lo, hi) => Math.min(Math.max(x, lo), hi);
function wLevel() { return clamp(Math.round(Number($("#w-niveau").value)) || 5, 4, 8); }
function wSigma() {
  const v = Number($("#w-sigma").value);
  return Number.isFinite(v) ? clamp(Math.round(v), 0, 50) : 10;
}
function wMethode() {
  return $("#w-h3").checked ? "h3" : ($("#w-station").checked ? "knmi" : null);
}

// zoals gui._weather_sub: wat er aan weer in de dataset zit
function weatherSub() {
  if (!st.opened) return "";
  const parts = [];
  if (st.wcols.includes("weerzone_h3")) parts.push(`H3 niveau ${wLevel()}, σ ${wSigma()} km`);
  else if (st.wcols.includes("weer_knmi_station")) parts.push("KNMI-station");
  if (st.wcols.includes("uhi")) parts.push("UHI");
  return parts.length ? parts.join(" + ") : "niet toegevoegd";
}

// de tekst van de facade heeft **vet**, !!oranje!! en ~~grijs~~ (nog onbekend): als elementen,
// nooit als HTML
function markup(text) {
  const frag = document.createDocumentFragment();
  for (const part of String(text == null ? "" : text).split(/(\*\*.+?\*\*|!!.+?!!|~~.+?~~)/)) {
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      frag.append(h("b", { text: part.slice(2, -2) }));
    } else if (part.startsWith("!!") && part.endsWith("!!") && part.length > 4) {
      frag.append(h("span", { class: "oranje", text: part.slice(2, -2) }));
    } else if (part.startsWith("~~") && part.endsWith("~~") && part.length > 4) {
      frag.append(h("span", { class: "onbekend", text: part.slice(2, -2) }));
    } else if (part) {
      frag.append(part);
    }
  }
  return frag;
}
function cardTable(rows) {
  const body = h("tbody");
  for (const r of rows || []) body.append(h("tr", {}, h("td", { text: r[0] }), h("td", {}, markup(r[1]))));
  return h("table", {}, body);
}
function renderCard(card) {
  $("#cel-titel").textContent = card.title || "";
  const box = $("#cel-tekst");
  box.replaceChildren(h("b", { class: "kopje", text: "Wat er ligt" }), cardTable(card.rows));
  if (card.after && card.after.length) {
    box.append(h("b", { class: "kopje", text: card.after_title || "" }), cardTable(card.after));
  }
}
function plainCard(title, text) {
  $("#cel-titel").textContent = title;
  $("#cel-tekst").replaceChildren(markup(text));
}
// zoals stappen.weather_band: de band over de kaart zolang er geen weerkolom van de getoonde stand is
function updateBand() {
  const band = $("#kaart-band");
  if (!band) return;
  const has = !st.opened ? false
    : kaart.mode === "h3" ? st.wcols.includes("weerzone_h3")
    : kaart.mode === "knmi" ? st.wcols.includes("weer_knmi_station")
    : st.wcols.includes("weerzone_h3") || st.wcols.includes("weer_knmi_station");
  band.hidden = has;
}

// ---- de kaart: projectie, tekenen ----

function buildGeo() {
  const L = kaart.layers;
  if (!L || !L.bbox) { kaart.geo = null; return; }
  const [x0, y0, x1, y1] = L.bbox;
  const kx = Math.cos(((y0 + y1) / 2) * Math.PI / 180);
  // wereldruimte: x = (lengte - x0) * kx, y = y1 - breedte (graden); zoomen en schuiven is dan één
  // transformatie en het tekenen kost bij slepen bijna niets
  const add = (path, ring) => {
    ring.forEach((p, i) => {
      const x = (p[0] - x0) * kx, y = y1 - p[1];
      if (i) path.lineTo(x, y); else path.moveTo(x, y);
    });
    return path;
  };
  const closed = (rings) => { const p = new Path2D(); for (const r of rings || []) { add(p, r); p.closePath(); } return p; };
  const land = new Path2D();
  for (const rings of L.land || []) for (const r of rings) { add(land, r); land.closePath(); }
  const borders = new Path2D();
  for (const r of L.borders || []) add(borders, r);
  kaart.geo = {
    x0, y1, kx, W: (x1 - x0) * kx, H: y1 - y0, add, closed,
    hasLand: !!(L.land && L.land.length), land, borders, base: closed(L.base),
    voronoi: (L.voronoi || []).map((v) => closed([v.ring])),
    stations: (L.stations || []).map((s) => [(s.lon - x0) * kx, y1 - s.lat]),
    pop: null, data: null, sel: null, near: null, heat: [],
  };
  buildCellPaths();
  buildSelPaths();
}
function buildCellPaths() {
  const g = kaart.geo;
  if (!g) return;
  const c = kaart.cells;
  const ok = c && c.level === kaart.level && kaart.mode === "h3";
  g.pop = !ok ? null : (kaart.level === 6 ? g.base : (kaart.level < 6 ? g.closed(c.population) : null));
  g.data = ok && c.dataset && c.dataset.length ? g.closed(c.dataset.map((d) => d.ring)) : null;
}
function buildSelPaths() {
  const g = kaart.geo;
  if (!g) return;
  const s = kaart.sel;
  g.sel = s && s.ring ? g.closed([s.ring]) : null;
  g.near = s && s.neighbours ? g.closed(s.neighbours) : null;
  g.heat = (kaart.heat || []).map((c) => ({ path: g.closed([c.ring]), w: Number(c.weight) || 0 }));
}

function frame() {
  const g = kaart.geo;
  const s = Math.min((kaart.w - 20) / g.W, (kaart.h - 20) / g.H) * kaart.zoom;
  return { g, s };
}
function toScreen(lon, lat) {
  const { g, s } = frame();
  return [10 + (lon - g.x0) * g.kx * s + kaart.panX, 10 + (g.y1 - lat) * s + kaart.panY];
}
function toGeo(x, y) {
  const { g, s } = frame();
  return [g.x0 + (x - 10 - kaart.panX) / (g.kx * s), g.y1 - (y - 10 - kaart.panY) / s];
}

function sizeMap() {
  const c = $("#kaart");
  if (!c) return;
  const w = c.clientWidth, hh = c.clientHeight;
  if (!w || !hh) return;                       // stap 5 is niet zichtbaar
  const dpr = window.devicePixelRatio || 1;
  // dezelfde plek in het midden houden als de kaart groter of kleiner wordt (zoals resizeEvent)
  let centre = null;
  if (kaart.geo && kaart.w && kaart.zoom > 1 && (kaart.w !== w || kaart.h !== hh)) {
    centre = toGeo(kaart.w / 2, kaart.h / 2);
  }
  kaart.w = w; kaart.h = hh; kaart.dpr = dpr;
  c.width = Math.round(w * dpr); c.height = Math.round(hh * dpr);
  if (centre) {
    const p = toScreen(centre[0], centre[1]);
    kaart.panX += w / 2 - p[0]; kaart.panY += hh / 2 - p[1];
  }
  drawMap();
}

// tekst over meerdere regels, om te passen in een breedte
function wrapText(ctx, text, maxW) {
  const lines = [];
  let line = "";
  for (const word of text.split(" ")) {
    const t = line ? line + " " + word : word;
    if (line && ctx.measureText(t).width > maxW) { lines.push(line); line = word; } else line = t;
  }
  if (line) lines.push(line);
  return lines;
}

function legendText() {
  if (kaart.mode === "knmi") {
    return "Voronoi: elk gekleurd vlak ligt dichter bij zijn KNMI-station (stip) dan bij elk ander.";
  }
  if (kaart.mode === "h3") {
    const parts = [];
    if (kaart.selected) {
      parts.push("dikke rand: de aangeklikte cel · dunne randen: haar zes buurcellen" +
        (kaart.heat.length ? " · oranje: waar de woning met 95% kans ligt" : ""));
    } else {
      parts.push(`klik een cel van niveau ${kaart.level} voor de uitleg`);
    }
    if (kaart.cells && kaart.cells.level === kaart.level && kaart.cells.dataset && kaart.cells.dataset.length) {
      parts.push("blauw: cellen die woningen uit je dataset als weerzone kregen");
    }
    parts.push("dubbelklik: heel Nederland");
    const t = parts.join(" · ");
    return t.charAt(0).toUpperCase() + t.slice(1) + ".";
  }
  return "Geen weerlocatie.";
}

function drawMap() {
  updateBand();
  const c = $("#kaart");
  if (!c || !kaart.w) return;
  const ctx = c.getContext("2d");
  if (!ctx) return;
  const d = kaart.dpr;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.fillStyle = KLEUR.achtergrond;
  ctx.fillRect(0, 0, c.width, c.height);
  const g = kaart.geo;
  if (!g) {
    ctx.setTransform(d, 0, 0, d, 0, 0);
    ctx.fillStyle = KLEUR.muted;
    ctx.font = '13px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(kaart.msg || "Kaart laden…", kaart.w / 2, kaart.h / 2);
    return;
  }
  const { s } = frame();
  const colours = (kaart.layers && kaart.layers.colours) || {};
  ctx.setTransform(d * s, 0, 0, d * s, d * (10 + kaart.panX), d * (10 + kaart.panY));
  const px = 1 / s;                             // één schermpunt in wereldeenheden
  ctx.lineJoin = "round";
  // water overal (buitenland blijft weg), het Nederlandse land erop, dan cellen, dan gemeentegrenzen
  if (g.hasLand) {
    ctx.fillStyle = colours.water || "#CFDDEA";
    ctx.fillRect(-1e3, -1e3, 2e3, 2e3);
    ctx.fillStyle = colours.land || "#F4F1EA";
    ctx.fill(g.land, "evenodd");
  }
  ctx.fillStyle = KLEUR.cel;
  ctx.fill(g.base);
  ctx.strokeStyle = "rgba(150,140,125,0.59)";
  ctx.lineWidth = 0.7 * px;
  ctx.stroke(g.borders);
  if (kaart.mode === "knmi") {
    // de stationsgebieden alleen op Nederlands land: de kust blijft leesbaar
    ctx.save();
    if (g.hasLand) ctx.clip(g.land, "evenodd");
    const pal = colours.stations && colours.stations.length ? colours.stations : ["#8DB3D9"];
    g.voronoi.forEach((path, i) => {
      ctx.globalAlpha = 0.47;
      ctx.fillStyle = pal[i % pal.length];
      ctx.fill(path);
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "rgba(60,60,60,0.7)";
      ctx.lineWidth = 1 * px;
      ctx.stroke(path);
    });
    ctx.restore();
    ctx.fillStyle = KLEUR.ink;
    for (const [x, y] of g.stations) {
      ctx.beginPath();
      ctx.arc(x, y, 3.5 * px, 0, 2 * Math.PI);
      ctx.fill();
    }
  }
  if (kaart.mode === "h3") {
    if (g.pop) {
      ctx.strokeStyle = "rgba(255,255,255,0.67)";
      ctx.lineWidth = 0.8 * px;
      ctx.stroke(g.pop);
    }
    if (g.near) {
      ctx.strokeStyle = "rgba(154,74,18,0.55)";
      ctx.lineWidth = 0.8 * px;
      ctx.stroke(g.near);
    }
    if (g.data) {
      ctx.fillStyle = "rgba(45,106,159,0.41)";
      ctx.fill(g.data);
      ctx.strokeStyle = KLEUR.navy;
      ctx.lineWidth = 1.2 * px;
      ctx.stroke(g.data);
    }
    if (g.sel) {
      // waar de woning werkelijk ligt, gegeven deze cel en sigma: donkerder is waarschijnlijker
      for (const hc of g.heat) {
        ctx.fillStyle = `rgba(200,80,20,${(clamp(60 + 180 * hc.w, 0, 255) / 255).toFixed(3)})`;
        ctx.fill(hc.path);
      }
      ctx.strokeStyle = KLEUR.oranje;
      ctx.lineWidth = 2.4 * px;
      ctx.stroke(g.sel);
    }
  }
  // stadsnamen en legenda in schermpunten
  ctx.setTransform(d, 0, 0, d, 0, 0);
  drawCities(ctx);
  drawLegend(ctx);
}

function drawCities(ctx) {
  ctx.font = 'bold 10.7px "Segoe UI", system-ui, sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const placed = [];
  for (const cty of (kaart.layers && kaart.layers.cities) || []) {       // de grootste eerst
    const [name, lon, lat] = cty;
    const [x, y] = toScreen(lon, lat);
    const w = ctx.measureText(name).width + 6;
    const r = { l: x - w / 2, t: y - 8, r: x + w / 2, b: y + 8 };
    if (r.r < 0 || r.l > kaart.w || r.b < 0 || r.t > kaart.h) continue;
    if (placed.some((o) => r.l < o.r && o.l < r.r && r.t < o.b && o.t < r.b)) continue;
    placed.push(r);
    ctx.fillStyle = "rgba(255,255,255,0.86)";
    for (const [dx, dy] of [[-1, 0], [1, 0], [0, -1], [0, 1]]) ctx.fillText(name, x + dx, y + dy);
    ctx.fillStyle = KLEUR.ink;
    ctx.fillText(name, x, y);
  }
}

function drawLegend(ctx) {
  ctx.font = '11.3px "Segoe UI", system-ui, sans-serif';
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";
  const lines = wrapText(ctx, legendText(), kaart.w - 20).slice(0, 2);
  const lh = 15;
  const top = kaart.h - 8 - lines.length * lh;
  ctx.fillStyle = "rgba(255,255,255,0.75)";
  ctx.fillRect(0, top - 3, kaart.w, kaart.h - top + 3);
  ctx.fillStyle = KLEUR.muted;
  lines.forEach((line, i) => ctx.fillText(line, 10, top + lh * (i + 1) - 3));
}

// ---- de kaart: bediening ----

function focusOn(lat, lon, km) {
  if (!kaart.geo) return;
  kaart.zoom = 1; kaart.panX = 0; kaart.panY = 0;
  const { s } = frame();
  kaart.zoom = clamp(Math.min(kaart.w, kaart.h) / (km / 111 * s), 1, 40);
  kaart.panX = 0; kaart.panY = 0;
  const here = toScreen(lon, lat);
  kaart.panX = kaart.w / 2 - here[0];
  kaart.panY = kaart.h / 2 - here[1];
  drawMap();
}

function canvasPoint(e) {
  const r = $("#kaart").getBoundingClientRect();
  return [e.clientX - r.left, e.clientY - r.top];
}

function bindMap() {
  const c = $("#kaart");
  c.addEventListener("wheel", (e) => {
    if (!kaart.geo) return;
    e.preventDefault();
    const [x, y] = canvasPoint(e);
    const before = toGeo(x, y);
    kaart.zoom = clamp(kaart.zoom * (e.deltaY < 0 ? 1.25 : 0.8), 1, 40);
    const after = toScreen(before[0], before[1]);
    kaart.panX += x - after[0]; kaart.panY += y - after[1];
    drawMap();
  }, { passive: false });
  c.addEventListener("pointerdown", (e) => {
    kaart.drag = canvasPoint(e); kaart.moved = false;
    try { c.setPointerCapture(e.pointerId); } catch (_) { /* dan zonder */ }
  });
  c.addEventListener("pointermove", (e) => {
    if (!kaart.drag) return;
    const p = canvasPoint(e);
    const dx = p[0] - kaart.drag[0], dy = p[1] - kaart.drag[1];
    if (Math.abs(dx) + Math.abs(dy) > 3) {
      kaart.moved = true;
      kaart.panX += dx; kaart.panY += dy;
      kaart.drag = p;
      drawMap();
    }
  });
  const up = (e) => {
    if (kaart.drag && !kaart.moved && kaart.geo && e.type === "pointerup") {
      const [x, y] = canvasPoint(e);
      const [lon, lat] = toGeo(x, y);
      mapClicked(lat, lon);
    }
    kaart.drag = null;
  };
  c.addEventListener("pointerup", up);
  c.addEventListener("pointercancel", up);
  c.addEventListener("dblclick", () => {                       // terug naar heel Nederland
    kaart.zoom = 1; kaart.panX = 0; kaart.panY = 0;
    drawMap();
  });
  if (typeof ResizeObserver === "function") new ResizeObserver(() => sizeMap()).observe(c);
  addEventListener("resize", debounce(sizeMap, 100));
}

function clearSelection() {
  kaart.token += 1;
  kaart.selected = null; kaart.selLevel = null; kaart.sel = null; kaart.heat = [];
  vgKaart.stop();
  buildSelPaths();
}

// zoals gui._cell_clicked
async function mapClicked(lat, lon) {
  if (kaart.mode === "knmi") {
    try {
      const r = await call("map_station", { lat, lon });
      if (r && r.station != null) plainCard(r.title || "", r.text || "");
    } catch (err) { plainCard("Er ging iets mis", err.message); }
    return;
  }
  if (kaart.mode !== "h3") return;
  const token = ++kaart.token;
  const level = kaart.level, sigma = kaart.sigma;
  try {
    const hit = await call("map_hit", { lat, lon, level });
    if (token !== kaart.token) return;
    kaart.selected = hit.cell; kaart.selLevel = level;
    kaart.sel = { ring: hit.ring, neighbours: hit.neighbours || [] };
    kaart.heat = [];
    buildSelPaths();
    drawMap();
    plainCard("Bezig met rekenen…", "Waar kan een woning in deze cel werkelijk liggen? Dat wordt nu uitgerekend.");
    vgKaart.start("waar de woning kan liggen uitrekenen");
    const r = await call("map_cell", { cell: hit.cell, sigma, p: st.p }, [], vgKaart);
    if (token !== kaart.token) return;             // intussen een andere cel aangeklikt
    kaart.sel = { ring: r.ring || hit.ring, neighbours: r.neighbours || hit.neighbours || [] };
    kaart.heat = r.heat || [];
    buildSelPaths();
    if (r.focus) focusOn(r.focus.lat, r.focus.lon, r.focus.km);
    else drawMap();
    if (r.card) renderCard(r.card);
  } catch (err) {
    if (token === kaart.token) plainCard("Er ging iets mis", err.message);
  } finally {
    if (token === kaart.token) vgKaart.stop();
  }
}

// ---- de kaart laden en verversen ----

function invalidateMap() {
  kaart.layers = null; kaart.geo = null; kaart.cells = null;
  clearSelection();
}

async function ensureMap() {
  if (!st.opened) return;
  if (kaart.layers) { drawMap(); return; }
  if (kaart.loading) return kaart.loading;
  kaart.msg = "Kaart laden…";
  drawMap();
  kaart.loading = (async () => {
    try {
      const layers = await call("map_layers");
      if (st.opened) {
        kaart.layers = layers;
        buildGeo();
        kaart.msg = "";
      }
    } catch (err) {
      kaart.layers = null; kaart.geo = null;
      kaart.msg = "Geen kaart: " + err.message;
      plainCard("Geen kaart", err.message);
    } finally {
      kaart.loading = null;
    }
    sizeMap();
    await refreshMapCells();
  })();
  return kaart.loading;
}

async function refreshMapCells() {
  if (!kaart.layers) return;
  if (kaart.mode !== "h3") { kaart.cells = null; buildCellPaths(); drawMap(); return; }
  const token = ++kaart.cellsToken;
  try {
    const r = await call("map_cells", { level: kaart.level });
    if (token !== kaart.cellsToken) return;
    kaart.cells = r;
  } catch (err) { kaart.cells = null; }
  buildCellPaths();
  drawMap();
}
const refreshMapCellsSoon = debounce(refreshMapCells, 250);

// zoals gui._weather_view: de tekst bij het niveau, wat aan mag, en de kaart in de juiste stand
function weatherView() {
  const level = wLevel();
  $("#w-niveaunoot").textContent =
    `Niveau ${level}: cellen van gemiddeld ${nr(H3_AREA[level])} km² (rand ${H3_EDGE[level].toFixed(1)} km). ` +
    (level >= 5 ? "Advies: niveau 5 met σ ≈ 10 km; zonder ruis is niveau 5 te herkenbaar." : "");
  const on = $("#w-h3").checked;
  for (const id of ["#w-niveau", "#w-sigma", "#w-meetellen"]) $(id).disabled = !on;
  kaart.mode = on ? "h3" : ($("#w-station").checked ? "knmi" : "none");
  kaart.level = level;
  kaart.sigma = wSigma();
  if (kaart.selected && kaart.selLevel !== level) clearSelection();
  buildCellPaths();
  drawMap();
  refreshMapCellsSoon();
  refreshRail();
}

function enterWeather() {
  weatherView();
  sizeMap();
  ensureMap();
}

// ---- toevoegen ----

function showWeatherTab(i) {
  document.querySelectorAll(".wtab").forEach((t, j) => t.setAttribute("aria-selected", String(i === j)));
  [0, 1, 2].forEach((j) => { $(`#wvak-${j}`).hidden = j !== i; });
}

function fillSelect(sel, values, current) {
  sel.replaceChildren(...values.map((v) => new Option(v === "" ? "" : v, v)));
  if (current != null && values.includes(current)) sel.value = current;
}

// zoals gui._add_column_rows: de nieuwe kolommen komen in stap 3, de bronkolommen worden weggelaten
function applyWeatherResult(r) {
  const body = document.querySelector("#kolommen tbody");
  if (body) {
    for (const c of r.remove || []) {
      const row = body.querySelector(`tr[data-kolom="${CSS.escape(c)}"]`);
      if (row) row.remove();
    }
    for (const c of r.direct || []) {
      const sel = body.querySelector(`select[data-column="${CSS.escape(c)}"]`);
      if (sel) sel.value = "direct";
    }
    for (const d of r.rows || []) body.append(columnRow(d, st.opened.catalogue || {}));
  }
  st.wcols = Object.keys(r.added || {});
  updateBand();
  st.result = null;                   // wat er getoetst was, gaat over een andere dataset
  st.steps = null;
  clearOutcome();
  busyButtons();
  refreshMapCells();
  refreshRail();
}

async function addWeather() {
  const method = wMethode();
  const status = $("#w-status");
  if (!method && !$("#u-aan").checked) {
    status.textContent = "Niets toe te voegen: kies een weerlocatie of UHI.";
    return;
  }
  const base = { source: $("#w-bron").value, link_cols: $("#koppel").value,
    gps: [$("#w-lat").value, $("#w-lon").value], level: wLevel(), sigma: wSigma() };
  const b = $("#w-toevoegen");
  b.disabled = true;
  status.textContent = "";
  try {
    vgWeer.start("weerlocatie toevoegen");
    let r = await call("weather", { ...base, method, count_noise: $("#w-meetellen").checked }, [], vgWeer);
    applyWeatherResult(r);
    status.textContent = r.status;
    if ($("#u-aan").checked) {
      // zonder eigen bestand gebruikt de tool de UHI uit de populatie
      const data = st.uhiFile ? await st.uhiFile.arrayBuffer() : null;
      vgWeer.start("UHI toevoegen");
      r = await call("uhi", { ...base, name: st.uhiFile ? st.uhiFile.name : null, data,
        class_width: Number($("#u-klas").value) || 0.5 }, data ? [data] : [], vgWeer);
      applyWeatherResult(r);
      status.textContent = r.status;
    }
  } catch (err) {
    status.replaceChildren(fout(err.message));
  } finally {
    vgWeer.stop();
    b.disabled = false;
  }
}

// ---- het weerspoor: "Weer al in de data?" ----

function traceFill(o) {
  traceState.info = o;
  $("#t-bestand").textContent = o.example ? `${o.name} (voorbeeld uit de oefenmodus)`
    : `${o.name}: ${o.files} bestand${o.files === 1 ? "" : "en"}`;
  const auto = "(automatisch)";
  const cols = o.columns || [];
  fillSelect($("#t-id"), [auto, ...cols], o.id_col || auto);
  fillSelect($("#t-tijd"), [auto, ...cols], o.time_col || auto);
  fillSelect($("#t-waarde"), [auto, ...cols], o.value_col || auto);
  const keys = o.key_columns || (st.opened ? st.opened.columns : []) || [];
  fillSelect($("#t-sleutel"), keys, o.key || keys[0]);
  $("#t-idfrom").value = o.id_from || "kolom";
  $("#t-patroon").value = o.pattern || "*";
  $("#t-steekproef").value = String(o.max_homes || 300);
  $("#t-run").disabled = false;
}
function traceReset() {
  traceState.info = null;
  $("#t-bestand").textContent = "geen bestand gekozen";
  for (const id of ["#t-id", "#t-tijd", "#t-waarde", "#t-sleutel"]) $(id).replaceChildren();
  $("#t-run").disabled = true;
  $("#t-status").textContent = "";
}

async function traceChosen(file) {
  if (!file) return;
  const status = $("#t-status");
  status.textContent = `${file.name} lezen…`;
  try {
    const data = await file.arrayBuffer();
    const o = await call("trace_open", { name: file.name, data, pattern: $("#t-patroon").value || "*" }, [data]);
    traceFill(o);
    status.textContent = "";
  } catch (err) {
    status.replaceChildren(fout(err.message));
  }
}

function traceOptions() {
  const auto = (v) => (v === "" || v === "(automatisch)" ? null : v);
  return { id_from: $("#t-idfrom").value, id_col: auto($("#t-id").value),
    time_col: auto($("#t-tijd").value), value_col: auto($("#t-waarde").value),
    pattern: $("#t-patroon").value || "*", max_homes: Number($("#t-steekproef").value) || 300,
    key: $("#t-sleutel").value };
}

// zoals gui.run_trace + _show_trace
async function runTrace() {
  if (!st.opened || !traceState.info) {
    $("#t-status").textContent = "open eerst een dataset en kies het bestand met weerreeksen";
    return;
  }
  const b = $("#t-run");
  b.disabled = true;
  traceState.busy = true;
  $("#t-status").textContent = "";
  vgSpoor.start("weerreeksen lezen");
  try {
    const name = traceState.info.example ? null : traceState.info.name;
    await call("trace", { name, options: traceOptions() }, [], vgSpoor);
    const r = await call("trace_apply", { level: wLevel(), sigma: wSigma() });
    applyWeatherResult(r);
    $("#w-status").textContent = r.status;
    $("#t-status").textContent = "";
    if (r.verdict != null) {
      $("#cel-titel").textContent = "Wat het weer verraadt";
      const box = $("#cel-tekst");
      const notes = r.findings || [];
      box.replaceChildren(h("b", { text: "Conclusie. " }), String(r.verdict), h("br"), h("br"),
        h("b", { text: "Advies. " }), String(r.advice || ""));
      if (notes.length) {
        box.append(h("br"), h("br"), h("b", { text: "Bevindingen." }));
        for (const n of notes) box.append(h("br"), "• " + n);
        if (r.more) box.append(h("br"), `… en nog ${r.more}`);
      }
    }
  } catch (err) {
    $("#t-status").replaceChildren(fout(err.message));
  } finally {
    vgSpoor.stop();
    traceState.busy = false;
    b.disabled = !traceState.info;
  }
}

// ---- opbouwen ----

function initWeather(o, example) {
  const numeric = o.numeric_columns || [];
  const gps = o.gps || ["", ""];
  fillSelect($("#w-lat"), ["", ...numeric], gps[0] || "");
  fillSelect($("#w-lon"), ["", ...numeric], gps[1] || "");
  const hasGps = !!(gps[0] && gps[1]);
  $("#w-bron").value = hasGps ? "gps" : "koppel";
  // met een manier om de woning te vinden: de aanbevolen weerlocatie voorstellen
  if (hasGps || $("#koppel").value) $("#w-h3").checked = true; else $("#w-geen").checked = true;
  st.wcols = [];
  st.uhiFile = null;
  $("#u-aan").checked = false;
  $("#u-bestand").textContent = "eigen bestand gebruiken (optioneel): csv/parquet met pc6, uhi";
  call("uhi_bron", {}).then((t) => { $("#u-bron").textContent = t; }).catch(() => {});
  $("#w-status").textContent = "";
  plainCard("Klik een cel op de kaart", "Scrol om in te zoomen, sleep om te schuiven.");
  clearSelection();
  kaart.cells = null;
  traceReset();
  if (example) {
    // zoals start_practice: het voorbeeld van de weerreeksen staat al klaar
    call("trace_open").then(traceFill).catch(() => {});
  }
  weatherView();
}
function resetWeather() {
  st.wcols = [];
  updateBand();
  invalidateMap();
  traceReset();
}

function buildWeather() {
  bindMap();
  document.querySelectorAll(".wtab").forEach((t, i) => {
    t.onclick = () => showWeatherTab(i);
    t.onkeydown = (e) => {
      const to = e.key === "ArrowRight" ? (i + 1) % 3 : e.key === "ArrowLeft" ? (i + 2) % 3 : null;
      if (to != null) { showWeatherTab(to); $(`#wtab-${to}`).focus(); }
    };
  });
  for (const id of ["#w-geen", "#w-station", "#w-h3", "#w-niveau", "#w-sigma"]) {
    $(id).addEventListener(id === "#w-niveau" || id === "#w-sigma" ? "input" : "change", weatherView);
  }
  $("#w-toevoegen").onclick = addWeather;
  $("#t-kies").onclick = () => $("#t-invoer").click();
  $("#t-invoer").onchange = (e) => { traceChosen(e.target.files[0]); e.target.value = ""; };
  $("#t-run").onclick = runTrace;
  $("#u-kies").onclick = () => $("#u-invoer").click();
  $("#u-invoer").onchange = (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    st.uhiFile = f;
    $("#u-bestand").textContent = f.name;
    $("#u-aan").checked = true;
  };
  weatherView();
}

boot();
