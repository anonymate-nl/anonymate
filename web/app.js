// De schil van AnonyMate in de browser: stappen, tabellen en knoppen. Al het rekenwerk gebeurt in
// worker.js (Pyodide); hier wordt alleen getoond en doorgegeven.
"use strict";

const $ = (s) => document.querySelector(s);
const BASE = new URL(".", location.href).href;
let worker = null;
let nextId = 1;
const pending = new Map();
let opened = null;      // antwoord van open_*: kolommen, detecties, catalogus
let result = null;      // antwoord van run/apply

// ---- de worker, gestart vanuit een blob:-URL zodat hij de policy van deze pagina erft ----

async function startWorker() {
  const src = await (await fetch("worker.js")).text();
  const url = URL.createObjectURL(new Blob([src], { type: "text/javascript" }));
  worker = new Worker(url);
  worker.onmessage = (e) => {
    const m = e.data;
    if (m.type === "status") return loadText(m.text);
    if (m.type === "progress") return searchProgress(m.fraction, m.text);
    const p = pending.get(m.id);
    pending.delete(m.id);
    m.ok ? p.resolve(m.result) : p.reject(new Error(m.error));
  };
}

function call(cmd, args = {}, transfer = []) {
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
  try {
    await startWorker();
    const v = await call("start", { base: BASE });
    $("#laadbalk").style.width = "100%";
    $("#laadtekst").textContent =
      `Klaar: Python ${v.python}, Pyodide ${v.pyodide}, AnonyMate ${v.anonymate}.`;
    $("#klaaroffline").hidden = false;
    setTimeout(() => { $("#laden").hidden = true; }, 600);
    go(0);
  } catch (err) {
    $("#laadtekst").innerHTML = "";
    $("#laadtekst").append(fout("Opstarten mislukt: " + err.message));
  }
}

function showOnline() {
  const on = navigator.onLine;
  $("#online").textContent = on ? "online" : "offline: de toets werkt gewoon door";
  $("#dot").classList.toggle("uit", !on);
}
addEventListener("online", showOnline);
addEventListener("offline", showOnline);

// ---- stappen ----

let current = 0;
function go(n) {
  current = n;
  document.querySelectorAll("[data-paneel]").forEach((el) => {
    el.hidden = Number(el.dataset.paneel) !== n;
  });
  document.querySelectorAll("#rail li").forEach((li) => {
    const i = Number(li.dataset.stap);
    li.classList.toggle("nu", i === n);
    li.classList.toggle("klaar", i < n);
  });
  window.scrollTo(0, 0);
}
function railText(n, text) {
  document.querySelector(`#rail li[data-stap="${n}"] span`).textContent = text;
}
function fout(text) {
  const s = document.createElement("span");
  s.className = "fout";
  s.textContent = text;
  return s;
}
function busy(button, on, text) {
  button.disabled = on;
  if (text) button.textContent = text;
}

// ---- stap 1: dataset ----

$("#oefen").onclick = async () => {
  const b = $("#oefen");
  busy(b, true, "Verzonnen Nederland maken…");
  try {
    showDataset(await call("open_practice"));
  } catch (err) {
    $("#dataset-melding").replaceChildren(fout(err.message));
  } finally {
    busy(b, false, "Oefenmodus: voorbeeldwoningen");
  }
};

async function openFile(file) {
  if (!file) return;
  $("#dataset-melding").textContent = `${file.name} lezen…`;
  try {
    const data = await file.arrayBuffer();
    showDataset(await call("open_file", { name: file.name, data }, [data]));
  } catch (err) {
    $("#dataset-melding").replaceChildren(fout(err.message));
  }
}
$("#kies").onclick = () => $("#bestand").click();
$("#bestand").onchange = (e) => openFile(e.target.files[0]);
const drop = $("#sleep");
drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = (e) => {
  e.preventDefault();
  drop.classList.remove("over");
  openFile(e.dataTransfer.files[0]);
};

const ROLE_NAMES = { direct: "direct identificerend (weglaten)", qid: "kenmerk dat iets verraadt",
  locatie: "verborgen locatie", afgeleid: "afgeleid (lekt hetzelfde)", meting: "meting, geen kenmerk" };

function showDataset(o) {
  opened = o;
  $("#dataset-melding").textContent =
    `${o.name}: ${o.records} woningen, ${o.columns.length} kolommen. ` +
    `Populatie: ${o.population.toLocaleString("nl-NL")} woningen (verzonnen Nederland).`;
  railText(0, `${o.name} · ${o.records} woningen`);
  const t = $("#kolommen");
  t.replaceChildren();
  t.insertAdjacentHTML("beforeend",
    "<thead><tr><th>kolom</th><th>voorstel</th><th>gebruiken als</th><th>waarom</th></tr></thead>");
  const body = document.createElement("tbody");
  for (const d of o.detections) {
    const tr = document.createElement("tr");
    const sel = document.createElement("select");
    sel.dataset.column = d.column;
    sel.setAttribute("aria-label", `rol van ${d.column}`);
    const opts = [["", "voorstel volgen"], ["geen", "geen kenmerk"], ["direct", "weglaten (direct)"]]
      .concat(Object.entries(o.catalogue).map(([k, label]) => [k, `kenmerk: ${label}`]));
    for (const [v, label] of opts) sel.add(new Option(label, v));
    tr.append(cell(d.column), cell(ROLE_NAMES[d.role] + (d.qid ? ` · ${d.qid}` : "")));
    const td = document.createElement("td");
    td.append(sel);
    tr.append(td, cell(d.reason || ""));
    body.append(tr);
  }
  t.append(body);
  go(1);
}
function cell(text) {
  const td = document.createElement("td");
  td.textContent = text == null ? "" : String(text);
  return td;
}

// ---- stap 2 en 3 ----

$("#naar-norm").onclick = () => {
  const n = Object.keys(mapping()).length;
  railText(1, n ? `${n} aangepast` : "voorstel gevolgd");
  go(2);
};
function mapping() {
  const m = {};
  document.querySelectorAll("#kolommen select").forEach((s) => {
    if (s.value) m[s.dataset.column] = s.value;
  });
  return m;
}

$("#toets").onclick = async () => {
  const b = $("#toets");
  busy(b, true, "Toetsen…");
  try {
    const p = Number($("#p").value);
    railText(2, $("#p").selectedOptions[0].textContent + " · " + $("#scenario").value);
    showResult(await call("run", { mapping: mapping(), p, scenario: $("#scenario").value }));
    $("#stappen-tabel").hidden = true;
    go(3);
  } catch (err) {
    b.after(fout(err.message));
  } finally {
    busy(b, false, "Toetsen");
  }
};

// ---- stap 4: uitkomst ----

const PALETTE = ["#1F3A5F", "#2D6A9F", "#5B8DB8", "#8DB3D6", "#B9D0E6", "#6C7A89", "#9AA6B2"];
const nl = (x, d = 1) => x == null ? "–" : Number(x).toLocaleString("nl-NL",
  { maximumFractionDigits: d, minimumFractionDigits: 0 });

function showResult(r) {
  result = r;
  const s = r.summary;
  $("#uitkomst-kop").textContent = `${s.ok} van de ${s.records} woningen publiceerbaar`;
  $("#uitkomst-sub").textContent =
    `Tegen ${nl(s.populatie, 0)} woningen (${s.afbakening}), norm p ≤ ${nl(s.p, 2)}, dus k ≥ ${s.k_drempel}.` +
    (r.direct.length ? ` Weggelaten: ${r.direct.join(", ")}.` : "");
  railText(3, `${s.ok} van ${s.records} publiceerbaar`);
  $("#tegels").replaceChildren(
    tegel("publiceerbaar", `${s.ok} · ${nl(100 * s.ok / Math.max(s.records, 1), 0)}%`),
    tegel("niet publiceren", s.risico),
    tegel("geen match", s.geen_match),
    tegel("gelijke woningen, mediaan", nl(s.k_mediaan, 0)),
  );
  // bits: hoeveel ja/nee-vragen elk kenmerk beantwoordt, tegen wat de norm overlaat
  const b = r.bits;
  // zoals de Windows-app: de kenmerken, dan wat nog te raden valt, en de norm als streep
  const rest = b.remaining_median || 0;
  const scale = Math.max(b.needed, b.per_column.reduce((a, c) => a + c.median, 0) + rest, 1);
  const bar = $("#bits");
  bar.replaceChildren();
  const labels = $("#bitlabels");
  labels.replaceChildren();
  b.per_column.forEach((c, i) => {
    const d = document.createElement("div");
    d.style.width = (100 * c.median / scale) + "%";
    d.style.background = PALETTE[i % PALETTE.length];
    d.title = `${c.column}: ${nl(c.median)} bits`;
    bar.append(d);
    const l = document.createElement("span");
    l.innerHTML = `<i style="background:${PALETTE[i % PALETTE.length]}"></i>`;
    l.append(`${c.column} ${nl(c.median)}${c.estimated ? " (geschat)" : ""}`);
    labels.append(l);
  });
  if (rest > 0) {
    const d = document.createElement("div");
    d.style.width = (100 * rest / scale) + "%";
    d.title = `nog te raden: ${nl(rest)} bits`;
    bar.append(d);
  }
  const norm = document.createElement("div");
  norm.className = "norm";
  norm.style.left = `calc(${100 * (scale - r.threshold.bits) / scale}% - 1px)`;
  norm.title = "tot hier mag een woning verraden: de rest moet te raden blijven";
  bar.append(norm);
  $("#bits-tekst").textContent =
    `${nl(b.needed)} bits wijzen één woning aan uit ${nl(s.populatie, 0)}. De norm vraagt dat ` +
    `er minstens ${nl(r.threshold.bits)} bits te raden blijven (de streep); per kenmerk de mediaan ` +
    `over de woningen. Nog te raden, mediaan: ${nl(rest)} bits.`;
  // per woning
  const t = $("#woningen");
  t.replaceChildren();
  const head = document.createElement("tr");
  r.columns.forEach((c) => { const th = document.createElement("th"); th.textContent = c; head.append(th); });
  const thead = document.createElement("thead");
  thead.append(head);
  const body = document.createElement("tbody");
  for (const row of r.rows) {
    const tr = document.createElement("tr");
    if (row.status !== "ok") tr.className = "risico";
    r.columns.forEach((c) => tr.append(cell(c === "status" ? STATUS[row[c]] || row[c] : row[c])));
    body.append(tr);
  }
  t.append(thead, body);
}
const STATUS = { ok: "publiceerbaar", risico: "te herleidbaar", geen_match: "geen match" };
function tegel(label, value) {
  const d = document.createElement("div");
  d.className = "tegel";
  const s = document.createElement("span");
  s.textContent = label;
  const b = document.createElement("b");
  b.textContent = value;
  d.append(s, b);
  return d;
}

// ---- generalisaties ----

function searchProgress(fraction, text) {
  $("#zoekbalk").style.width = Math.round(100 * fraction) + "%";
  $("#zoektekst").textContent = text || "";
}

$("#zoek").onclick = async () => {
  const b = $("#zoek");
  busy(b, true, "Zoeken…");
  $("#zoekvoortgang").hidden = false;
  searchProgress(0, "Zoeken naar de stap die de meeste woningen oplevert per verloren detail…");
  try {
    const { steps } = await call("suggest");
    const t = $("#stappen");
    t.replaceChildren();
    t.insertAdjacentHTML("beforeend", "<thead><tr><th>stap</th><th>publiceerbaar</th>" +
      "<th>k, mediaan</th><th>informatieverlies</th><th></th></tr></thead>");
    const body = document.createElement("tbody");
    steps.forEach((st, i) => {
      const tr = document.createElement("tr");
      tr.append(cell(st.stap), cell(`${st.ok} (${nl(st["publiceerbaar_%"], 0)}%)`),
        cell(nl(st.k_mediaan, 0)), cell(nl(st.informatieverlies, 2)));
      const td = document.createElement("td");
      if (i > 0) {
        const k = document.createElement("button");
        k.className = "knop";
        k.textContent = "tot hier toepassen";
        k.onclick = async () => {
          busy(k, true);
          try { showResult(await call("apply", { step: i })); $("#stappen-tabel").hidden = true; }
          catch (err) { td.append(fout(err.message)); }
        };
        td.append(k);
      }
      tr.append(td);
      body.append(tr);
    });
    t.append(body);
    $("#stappen-tabel").hidden = false;
  } catch (err) {
    b.after(fout(err.message));
  } finally {
    busy(b, false, "Generalisaties zoeken");
    $("#zoekvoortgang").hidden = true;
  }
};

// ---- downloaden: een Blob in dit venster, niets gaat naar een server ----

$("#download").onclick = async () => {
  const b = $("#download");
  busy(b, true, "Rapport maken…");
  try {
    const bytes = await call("export");
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/zip" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = (opened ? opened.name.replace(/\.[^.]+$/, "") : "dataset") + "_anonymate.zip";
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  } catch (err) {
    b.after(fout(err.message));
  } finally {
    busy(b, false, "Uitkomst downloaden (zip)");
  }
};

boot();
