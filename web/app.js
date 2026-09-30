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
  p: 0.09,
  k: 11,
  current: 0,         // getoonde stap
  furthest: 0,        // verste stap die bezocht is (voor de vinkjes in de rail)
  busy: false,
  result: null,       // antwoord van run/suggest/apply
  steps: null,        // de generalisatiestappen van suggest
  chosenStep: -1,
  adopted: false,
  selectedRow: -1,
  regionText: "heel Nederland",
  started: 0, fraction: null, progressText: "", tick: null,
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
    if (m.type === "status") return loadText(m.text);
    if (m.type === "progress") return onProgress(m.fraction, m.text);
    const p = pending.get(m.id);
    pending.delete(m.id);
    if (!p) return;
    if (m.ok) p.resolve(m.result);
    else { const err = new Error(m.error); err.technical = m.technical; p.reject(err); }
  };
}

// Alles behalve "start" wacht tot de rekenkern klaar is: wie eerder klikt, staat in de rij.
async function call(cmd, args = {}, transfer = []) {
  if (cmd !== "start") await ready;
  return new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    worker.postMessage({ id, cmd, args }, transfer);
  });
}

// ---- opstarten ----

let loadStep = 0;
function loadText(text) {
  $("#laadtekst").textContent = text;
  loadStep += 1;
  $("#laadbalk").style.width = Math.min(90, 10 + loadStep * 25) + "%";
}

async function boot() {
  const csp = document.querySelector('meta[http-equiv="Content-Security-Policy"]');
  $("#csp").textContent = csp ? csp.content : "";
  showOnline();
  buildStatic();
  go(0);      // stap 1 staat er meteen; de rekenkern laadt ondertussen
  try {
    await startWorker();
    const v = await call("start", { base: BASE });
    isReady = true;
    markReady();
    $("#laadbalk").style.width = "100%";
    $("#laadtekst").textContent =
      `Klaar: Python ${v.python}, Pyodide ${v.pyodide}, AnonyMate ${v.anonymate}.`;
    window.__timings = v.timings;
    console.log("opstarten (s): " + JSON.stringify(v.timings));
    $("#klaaroffline").hidden = false;
    setTimeout(() => { $("#laden").hidden = true; }, 600);
  } catch (err) {
    markFailed(err);
    $("#laadtekst").replaceChildren(fout("Opstarten mislukt: " + err.message));
  }
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
  st.current = n;
  if (st.opened) st.furthest = Math.max(st.furthest, n);
  document.querySelectorAll("[data-paneel]").forEach((el) => {
    el.hidden = Number(el.dataset.paneel) !== n;
  });
  window.scrollTo(0, 0);
  refreshRail();
  if (n === 6) redrawBits();
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
    "volgt",
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
    li.querySelector("button").disabled = i > 0 && !has;
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
    ["Asol", "A_sol", "m²", 0, 200, "effectief zonoppervlak: hoeveel zonnewarmte binnenkomt"]];
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
  $("#lock").onclick = lockNorm;
  $("#naar-norm").onclick = () => go(1);
  $("#naar-kolommen").onclick = () => go(2);
  $("#naar-signatuur").onclick = () => go(3);
  $("#naar-aanvaller-a").onclick = () => go(5);      // stap 5 (weerlocatie) volgt: overslaan
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
  const r = await call("set_region", regionState());
  st.regionText = r.text;
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
  $("#zoek").disabled = !ready;
  $("#verken").disabled = !ready;
  $("#opslaan").disabled = !st.result || st.busy;
  $("#overnemen").disabled = st.busy || !st.steps || st.steps.length < 2 || st.adopted;
  $("#kies").disabled = st.busy;
  $("#oefen").disabled = st.busy;
  $("#naar-norm").disabled = !st.opened;
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
    const o = await call("open_practice");
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
    await loadDataset(await call("open_file", { name: file.name, data }, [data]), false);
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
  noot.hidden = example;
  noot.textContent = "Let op: de echte populatie volgt in een latere versie. Tot dan toets je ook " +
    "een eigen bestand tegen het verzonnen Nederland van de oefenmodus: de uitkomst zegt niets " +
    "over echte woningen.";
  $("#oefenbalk").hidden = !o.practice;
  regionRestore();
  st.regionText = o.region || "heel Nederland";
  buildColumns(o);
  $("#koppel").value = (o.link_columns || []).join(",");
  renderSignature();
  setNormMarks(o.norm);
  setP(o.norm ? o.norm.default : 0.09);
  $("#p").disabled = false;
  $("#p-schuif").disabled = false;
  $("#lock").disabled = false;
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
  for (const d of o.detections) {
    const sel = h("select", { "data-column": d.column, "aria-label": `rol van ${d.column}` });
    sel.add(new Option("(geen)", "geen"));
    sel.add(new Option("(weglaten)", "direct"));
    for (const [k, label] of Object.entries(o.catalogue)) {
      const opt = new Option(k, k);
      opt.title = label;
      sel.add(opt);
    }
    sel.value = d.default;             // voorgeselecteerd zoals het Windows-programma
    sel.onchange = refreshRail;
    body.append(h("tr", { "data-kolom": d.column },
      h("td", { text: d.column }), h("td", { text: d.proposal }), h("td", {}, sel),
      h("td", { class: "reden", text: d.reason || "" })));
  }
  t.append(body);
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
      "in de dataset zitten." };
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

async function lockNorm() {
  try {
    const n = await call("lock_norm", { p: st.p });
    st.locked = true;
    st.p = n.p;
    st.k = n.k;
    $("#p").disabled = true;
    $("#p-schuif").disabled = true;
    $("#lock").disabled = true;
    $("#lock-tekst").textContent = n.label;
    renderNorm(n);
    busyButtons();
  } catch (err) {
    $("#lock-tekst").replaceChildren(fout(err.message));
  }
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
  const total = Math.max(b.needed, parts.reduce((a, p) => a + p.median, 0) + b.remaining_median);
  const scale = w / total;
  const [y, hh] = [8, 24];
  const svg = s("svg", { class: "tekening", width: W, height: 92, viewBox: `0 0 ${W} 92`, role: "img" });
  const tip = [...parts.map((p) => `${p.column}: ${nlf(p.median)} bits`),
    `nog te gaan: ${nlf(b.remaining_median)} bits`,
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
  const rw = b.remaining_median * scale;
  svg.append(s("rect", { x, y, width: Math.max(rw, 0), height: hh, fill: "var(--rest)",
    stroke: "var(--rest-rand)" }));
  let text = `nog te gaan: ${nlf(b.remaining_median)}`;
  if (breedte(text) + 10 > rw) text = nlf(b.remaining_median);
  if (breedte(text) + 8 <= rw) {
    svg.append(s("text", { x: x + 6, y: y + hh / 2 + 4, "font-size": 11.3, text }));
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
  const [top, base] = [18, hgt - 22];
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

// informatieverlies tegen publiceerbaar, met de 95%-lijn en de gekozen stap
function drawTradeoff(rows, selected, targetPct = 95) {
  const box = $("#afweging");
  box.replaceChildren();
  if (!rows.length) return;
  const [w, hgt] = [720, 330];
  const [left, right, top, bottom] = [48, w - 16, 16, hgt - 34];
  const svg = s("svg", { class: "tekening", width: w, height: hgt, viewBox: `0 0 ${w} ${hgt}`,
    role: "img", style: "width:100%" });
  svg.append(s("title", { text: "Informatieverlies: gemiddeld over woningen en kenmerken. 0% = alle " +
    "waarden exact, 100% = alle kenmerken weggelaten. Een klasse van 10 jaar bij bouwjaren van " +
    "1900 tot 2020 kost bijvoorbeeld zo'n 8%." }));
  const hi = Math.max(...rows.map((r) => r.loss)) * 100;
  const tick = [1, 2, 5, 10, 20, 25].find((t) => hi / t <= 5) || 25;
  const topX = Math.max(tick, Math.ceil(hi / tick) * tick);
  const pt = (pct, loss) => ({
    x: left + loss * 100 / topX * (right - left - 40),
    y: bottom - pct / 100 * (bottom - top) });
  const aslijn = { stroke: "var(--as)", "stroke-width": 1 };
  svg.append(s("line", { x1: left, y1: bottom, x2: right, y2: bottom, ...aslijn }));
  svg.append(s("line", { x1: left, y1: top, x2: left, y2: bottom, ...aslijn }));
  const stil = { class: "stil", "font-size": 11.3 };
  svg.append(s("text", { x: left - 6, y: top - 6 + 11, "text-anchor": "end", ...stil, text: "100%" }));
  svg.append(s("text", { x: left - 6, y: bottom - 8 + 11, "text-anchor": "end", ...stil, text: "0%" }));
  svg.append(s("text", { transform: `translate(12,${(top + bottom) / 2}) rotate(-90)`,
    "text-anchor": "middle", ...stil, text: "publiceerbaar" }));
  for (let v = 0; v <= topX; v += tick) {
    const x = left + v / topX * (right - left - 40);
    svg.append(s("line", { x1: x, y1: bottom, x2: x, y2: bottom + 4, ...aslijn }));
    if (v) svg.append(s("text", { x, y: bottom + 5 + 11, "text-anchor": "middle", ...stil, text: `${v}%` }));
  }
  svg.append(s("text", { x: right, y: bottom + 18 + 11, "text-anchor": "end", ...stil,
    text: "informatieverlies →" }));
  const ty = bottom - targetPct / 100 * (bottom - top);
  svg.append(s("line", { x1: left, y1: ty, x2: right, y2: ty, stroke: "var(--orange-ink)",
    "stroke-width": 1.2, "stroke-dasharray": "5 4" }));
  const pts = rows.map((r) => pt(r.pct, r.loss));
  svg.append(s("polyline", { points: pts.map((q) => `${q.x},${q.y}`).join(" "), fill: "none",
    stroke: "var(--blue)", "stroke-width": 2.2, "stroke-linejoin": "round" }));
  // de punten zelf zijn ook obstakels: een label komt nooit op een punt te liggen
  const placed = pts.map((q) => ({ l: q.x - 8, t: q.y - 8, r: q.x + 8, b: q.y + 8 }));
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

// ---- stap 7: uitkomst ----

const STATUS = { ok: "publiceerbaar", risico: "te herleidbaar", geen_match: "geen match" };

function showTab(i) {
  document.querySelectorAll(".tab").forEach((t, j) => t.setAttribute("aria-selected", String(i === j)));
  [0, 1, 2].forEach((j) => { $(`#tabvak-${j}`).hidden = j !== i; });
}

function tegel(label, value) {
  return h("div", { class: "tegel" }, h("span", { text: label }), h("b", { text: value }));
}

function clearOutcome() {
  $("#uitkomst-kop").textContent = "Nog niet getoetst";
  $("#tegels").replaceChildren();
  $("#bits").replaceChildren();
  $("#bits-tekst").textContent = "";
  $("#histogram").replaceChildren();
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
}

// zoals gui._show_assessment
function showAssessment(r) {
  st.result = r;
  $("#foutmelding").hidden = true;
  $("#uitkomst-kop").textContent = r.title;
  $("#tegels").replaceChildren(
    tegel("publiceerbaar", r.stats.ok), tegel("niet publiceren", r.stats.risk),
    tegel("gelijke woningen, mediaan", r.stats.k), tegel("nog te raden, mediaan", r.stats.bits));
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
  table.append(h("thead", {}, h("tr", {}, ...t.columns.map((c) => h("th", { text: c })))));
  const body = h("tbody");
  const n = Math.min(t.rows.length, MAX_ROWS);
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) {
    const tr = h("tr", { class: t.status[i], "data-i": i, tabindex: -1 });
    for (const v of t.rows[i]) tr.append(h("td", { text: v }));
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
    st.started = performance.now();
    st.fraction = null;
    st.progressText = "";
    $("#voortgang").hidden = false;
    $("#voortgangbalk").classList.add("onbepaald");
    $("#zoekbalk").style.width = "0%";
    $("#voortgangtekst").textContent = "bezig…";
    st.tick = setInterval(() => onProgress(null, null), 1000);
  } else {
    $("#voortgang").hidden = true;
    clearInterval(st.tick);
  }
  busyButtons();
}

const clock = (sec) => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, "0")}`;
// zoals gui._on_progress: voortgang van de berekening (fractie 0..1, tekst), of een tik van de klok
function onProgress(fraction, text) {
  if (!st.busy) return;
  const elapsed = (performance.now() - st.started) / 1000;
  if (fraction != null) {
    st.fraction = fraction;
    st.progressText = text;
    $("#voortgangbalk").classList.remove("onbepaald");
    $("#zoekbalk").style.width = Math.round(100 * fraction) + "%";
  }
  const parts = [st.progressText || "bezig", `${clock(elapsed)} bezig`];
  if (st.fraction && st.fraction > 0.05) parts.push(`nog ongeveer ${clock(elapsed * (1 - st.fraction) / st.fraction)}`);
  $("#voortgangtekst").textContent = parts.join(" · ");
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
  setBusy(true);
  try {
    await sendRegion();
    showAssessment(await call("run", inputs()));
  } catch (err) {
    failed(err);
  } finally {
    setBusy(false);
  }
}

async function runSuggest() {
  if (!st.locked) return failed("Leg eerst de privacynorm vast (stap 2).");
  go(6);
  setBusy(true);
  try {
    await sendRegion();
    const r = await call("suggest", inputs());
    showAssessment(r);
    showSuggestion(r);
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
  drawTradeoff(st.steps, i);
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
    const r = await call("apply", { step: st.chosenStep });
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
  try {
    const bytes = await call("export");
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
    b.textContent = "Opslaan (zip)";
    busyButtons();
  }
}

boot();
