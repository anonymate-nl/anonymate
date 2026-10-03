// AnonyMate in de browser: de rekenkern in Pyodide, in een Web Worker.
//
// De pagina start deze worker vanuit een blob:-URL, zodat hij dezelfde Content-Security-Policy
// erft als de pagina (GitHub Pages kan geen headers meegeven; een worker van een gewone URL zou
// zonder policy draaien). Daarom zijn alle URL's hier absoluut: de pagina geeft zijn eigen adres
// mee in het eerste bericht.
//
// Berichten van de pagina: {id, cmd, args}. Antwoord: {id, ok, result} of {id, ok: false, error}.
// Tussendoor: {type: "status", text} en {type: "progress", id, fraction, text}; dat laatste van elke
// lange opdracht, zodat de pagina de voortgang bij de juiste balk toont (zonder fraction: onbekend).

// Pyodide staat naast de pagina (pyodide/, gebouwd door web/maak.py; de versie staat daar vastgepind
// en in wheel.json): geen CDN, alles van dezelfde herkomst.
// h3 en pyarrow zijn er bij het opstarten niet bij: de oefenpopulatie komt kant-en-klaar als
// Parquet (DuckDB leest die zelf) en Parquet lezen gaat via DuckDB (docs/werk/webversie.md, "Opstarten").
// h3 en wat de latere stappen verder nodig hebben, komt daarna op de achtergrond binnen (zie
// achtergrond); een aanroep die het eerder nodig heeft, wacht op diezelfde belofte.
const PACKAGES = ["numpy", "pandas", "duckdb"];
const POPULATIE = "/tmp/oefenpopulatie.parquet";

let py = null;
let web = null;
let populatieKlaar = false;

const status = (text, fase) => postMessage({ type: "status", text, fase });

// hoe lang elke fase van het opstarten duurt, in seconden (kladbloknotitie 14)
const timings = {};
let mark = performance.now();
function lap(name) {
  const now = performance.now();
  timings[name] = Math.round(now - mark) / 1000;
  mark = now;
}
// een ophaalactie die naast andere loopt: hoe lang hij zelf duurde, buiten de rondetijden om
async function timed(name, promise) {
  const t0 = performance.now();
  const out = await promise;
  timings[name] = Math.round(performance.now() - t0) / 1000;
  return out;
}

// ---- laden op de achtergrond ----
// Alles wat een latere stap nodig heeft, maar het opstarten niet: één gedeelde belofte per onderdeel,
// zodat een aanroep die h3 nodig heeft terwijl het nog laadt, op dezelfde belofte wacht (nooit twee
// keer laden). Een mislukking wordt gemeld en vergeten: de volgende aanroep probeert het opnieuw.
const ACHTERGROND = ["h3", "modules"];
const bg = new Map();                                  // naam -> belofte van dat onderdeel
const bgStaat = Object.fromEntries(ACHTERGROND.map((n) => [n, "wacht"]));   // wacht|laden|klaar|mislukt
const bgFouten = {};
let bgStart = null;                                    // performance.now() bij het begin van start

function meldAchtergrond() {
  postMessage({ type: "achtergrond", staat: { ...bgStaat }, fouten: { ...bgFouten },
                timings: { ...timings } });
}

function achtergrond(naam, laad) {
  if (bg.has(naam)) return bg.get(naam);
  bgStaat[naam] = "laden";
  delete bgFouten[naam];
  meldAchtergrond();
  const t0 = performance.now();
  const belofte = (async () => {
    await laad();
    timings["achtergrond_" + naam] = Math.round(performance.now() - t0) / 1000;
    bgStaat[naam] = "klaar";
    if (ACHTERGROND.every((n) => bgStaat[n] === "klaar") && bgStart !== null) {
      timings.alles_geladen = Math.round(performance.now() - bgStart) / 1000;
    }
    meldAchtergrond();
  })().catch((err) => {
    bg.delete(naam);                                   // de volgende aanroep probeert het opnieuw
    bgStaat[naam] = "mislukt";
    bgFouten[naam] = String(err && err.message || err);
    meldAchtergrond();
    throw err;
  });
  bg.set(naam, belofte);
  return belofte;
}

// het pakket h3 (kaart, weerlocatie, weerspoor)
const laadH3 = () => achtergrond("h3", () => py.loadPackage("h3"));

// de Python-modules van de latere stappen alvast importeren (h3 zit erin), zodat de eerste klik op
// de kaart of het weerspoor daar niet op wacht; de gegevens zelf blijven tot dan ongelezen
const laadModules = () => achtergrond("modules", async () => {
  await laadH3();
  await new Promise((r) => setTimeout(r, 0));          // eerst de berichten van de pagina
  py.runPython("import h3, zoneinfo, anonymate.kaart, anonymate.weerspoor, anonymate.link, " +
    "anonymate.report, anonymate.representativiteit, anonymate.voorbeeld");
});

// alles op de achtergrond; mislukkingen zijn niet fataal (de aanroep die het nodig heeft, probeert
// het opnieuw)
async function laadAchtergrond() {
  await Promise.allSettled([laadH3(), laadModules()]);
  return { staat: { ...bgStaat }, fouten: { ...bgFouten }, timings: { ...timings } };
}

async function bytes(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}

async function start(base) {
  mark = performance.now();
  bgStart = mark;
  status("Python en rekenbibliotheken laden (eenmalig ongeveer 20 MB)…", "python_pakketten");
  const pyodide = new URL("pyodide/", base).href;
  importScripts(pyodide + "pyodide.js");
  // de wheel en de oefenpopulatie komen binnen terwijl Python en de pakketten laden
  const wheel = timed("wheel_ophalen", (async () => {
    const info = await (await fetch(new URL("wheel.json", base))).json();
    return { info, data: await bytes(new URL(info.wheel, base)) };
  })());
  const populatie = timed("populatie_ophalen",
    bytes(new URL("oefenpopulatie.parquet", base)).catch(() => null));
  // wie de pagina alleen met de wheel host, krijgt de oefenpopulatie dan in het geheugen gemaakt
  wheel.catch(() => {});
  py = await loadPyodide({ indexURL: pyodide, packages: PACKAGES });
  lap("python_pakketten");
  status("AnonyMate uitpakken…", "wheel");
  const { info, data } = await wheel;
  // geen micropip: de wheel is een zip, en alles wat hij nodig heeft, staat hierboven al
  const site = py.runPython("import site; site.getsitepackages()[0]");
  py.unpackArchive(data, "wheel", { extractDir: site });
  const pop = await populatie;
  if (pop) {
    py.FS.mkdirTree("/tmp");
    py.FS.writeFile(POPULATIE, pop);
    populatieKlaar = true;
  }
  lap("wheel");
  status("AnonyMate starten…", "import");
  web = py.pyimport("anonymate.web");
  lap("import");
  return { python: py.runPython("import sys; sys.version.split()[0]"),
           pyodide: py.version, anonymate: info.version, timings };
}

function toJs(x) {
  if (x && typeof x.toJs === "function") {
    const out = x.toJs({ dict_converter: Object.fromEntries, create_pyproxies: false });
    x.destroy();
    return out;
  }
  return x;
}

// opdrachten die H3 nodig hebben: de kaart en de weerlocatie. h3 komt pas hier binnen (eenmalig),
// Het weerspoor rekent de KNMI-uren om naar Europe/Amsterdam; die ene tijdzone levert de wheel
// zelf mee (anonymate.web.alleen_amsterdam), dus het pakket tzdata is niet nodig.
const NEEDS_H3 = new Set(["map_layers", "map_cells", "map_hit", "map_cell", "map_station", "weather",
  "uhi", "trace", "trace_apply"]);
async function ensureH3() {
  if (!bg.has("h3")) status("h3 laden…");
  await laadH3();
}

async function call(cmd, args, id) {
  try {
    if (NEEDS_H3.has(cmd) && py) await ensureH3();
    return await run(cmd, args, id);
  } catch (err) {
    // een functie die h3 nodig heeft (Weerlocatie, verzonnen plaatsen): nu pas laden, en opnieuw
    if (!/No module named 'h3'/.test(String(err && err.message || err))) throw err;
    bg.delete("h3");
    await ensureH3();
    return run(cmd, args, id);
  }
}

// de voortgangsmelding van een lange opdracht (Python roept hem aan met fractie en tekst)
const voortgang = (id) => (fraction, text) => postMessage({ type: "progress", id, fraction, text });

// wat run en suggest van de pagina krijgen: de volledige mapping, de aanvaller en de afbakening
function invoer(args) {
  return {
    mapping: args.mapping ? py.toPy(args.mapping) : null,
    scenario: args.scenario ?? null,
    scope: args.scope ?? null,
  };
}

// de argumenten van weather en uhi: bron, koppelkolommen of GPS-kolommen, methode, niveau, sigma
function weerinvoer(args) {
  const out = {
    source: args.source || "koppel", link_cols: args.link_cols || "",
    gps: py.toPy(args.gps || ["", ""]), level: args.level ?? 5, sigma: args.sigma ?? 10,
  };
  if (args.method !== undefined) { out.method = args.method || null; out.count_noise = !!args.count_noise; }
  return out;
}

// het bestand of de zip met weerreeksen: alleen in het geheugen van deze worker, tot het volgende
let reeksPad = null;
function bewaarReeks(name, data) {
  py.FS.mkdirTree("/tmp/reeks");
  if (reeksPad) { try { py.FS.unlink(reeksPad); } catch (_) { /* al weg */ } }
  reeksPad = "/tmp/reeks/" + name.replace(/[\\/]/g, "_");
  py.FS.writeFile(reeksPad, new Uint8Array(data));
  return reeksPad;
}

function wisReeks() {
  if (reeksPad) { try { py.FS.unlink(reeksPad); } catch (_) { /* al weg */ } }
  reeksPad = null;
  return null;
}

async function run(cmd, args, id) {
  switch (cmd) {
    case "start":
      return start(args.base);
    case "background":
      return laadAchtergrond();
    case "open_practice": {
      mark = performance.now();
      const progress = voortgang(id);
      const out = toJs(web.open_practice.callKwargs({
        population_path: populatieKlaar ? POPULATIE : null, progress }));
      lap("oefenpopulatie");
      out.timings = timings;
      return out;
    }
    case "open_file": {
      // het bestand staat alleen in het geheugen van deze worker, en open_file ruimt het op
      py.FS.mkdirTree("/tmp/invoer");
      const path = "/tmp/invoer/" + args.name.replace(/[\\/]/g, "_");
      py.FS.writeFile(path, new Uint8Array(args.data));
      return toJs(web.open_file(path, args.name));
    }
    case "open_population": {
      // de echte populatie (fase 3): het bestand wordt alleen-lezen gekoppeld (WORKERFS), niet
      // gekopieerd; DuckDB leest er alleen de kolommen en rijgroepen uit die een toets nodig heeft
      let file = args.file;
      if (!file && args.url) {
        const r = await fetch(new URL(args.url, args.base));
        if (!r.ok) throw new Error("populatie niet gevonden: " + args.url);
        file = new File([await r.blob()], args.url.split("/").pop());
      }
      const dir = "/populatie";
      try { py.FS.unmount(dir); } catch (err) { /* nog niet gekoppeld */ }
      py.FS.mkdirTree(dir);
      py.FS.mount(py.FS.filesystems.WORKERFS, { files: [file] }, dir);
      const t0 = performance.now();
      const out = toJs(web.open_population.callKwargs({
        path: dir + "/" + file.name, sources: args.sources ? py.toPy(args.sources) : null }));
      out.seconden = Math.round(performance.now() - t0) / 1000;
      return out;
    }
    case "add_eponline": {
      // fase 4: het totaalbestand van EP-online dat de gebruiker sleepte, alleen-lezen gekoppeld
      // (WORKERFS): Python leest de zip zonder hem eerst in het geheugen te laden
      const dir = "/eponline";
      try { py.FS.unmount(dir); } catch (err) { /* nog niet gekoppeld */ }
      py.FS.mkdirTree(dir);
      py.FS.mount(py.FS.filesystems.WORKERFS, { files: [args.file] }, dir);
      try {
        return toJs(web.add_eponline.callKwargs({
          path: dir + "/" + args.file.name, name: args.file.name, progress: voortgang(id) }));
      } finally {
        try { py.FS.unmount(dir); } catch (err) { /* al weg */ }
      }
    }
    case "stop_practice":
      return toJs(web.stop_practice());
    case "set_region":
      return toJs(web.set_region.callKwargs({
        heel_nederland: !!args.heel, provincies: py.toPy(args.provincies || []),
        gemeenten: args.gemeenten || "",
      }));
    case "norm":
      return toJs(web.norm(args.p));
    case "lock_norm":
      return toJs(web.lock_norm(args.p));
    case "run":
      return toJs(web.run.callKwargs({ ...invoer(args), progress: voortgang(id) }));
    case "record":
      return toJs(web.record(args.index));
    case "target_text":
      return web.target_text(args.share);
    case "suggest":
      return toJs(web.suggest.callKwargs({ ...invoer(args), target_share: args.share ?? null,
        progress: voortgang(id) }));
    case "apply":
      return toJs(web.apply(args.step));
    case "map_layers":
      return toJs(web.map_layers());
    case "map_cells":
      return toJs(web.map_cells(args.level));
    case "map_hit":
      return toJs(web.map_hit(args.lat, args.lon, args.level));
    case "map_cell":
      return toJs(web.map_cell.callKwargs({ cell: args.cell, sigma: args.sigma, p: args.p ?? null,
        progress: voortgang(id) }));
    case "map_station":
      return toJs(web.map_station(args.lat, args.lon));
    case "weather":
      return toJs(web.weather.callKwargs({ ...weerinvoer(args), progress: voortgang(id) }));
    case "uhi_bron":
      return web.uhi_bron();
    case "uhi": {
      // het bestand staat alleen in het geheugen van deze worker; uhi() ruimt het op.
      // Zonder bestand gebruikt uhi() de UHI uit de populatie.
      let path = null;
      if (args.data) {
        py.FS.mkdirTree("/tmp/uhi");
        path = "/tmp/uhi/" + args.name.replace(/[\\/]/g, "_");
        py.FS.writeFile(path, new Uint8Array(args.data));
      }
      return toJs(web.uhi.callKwargs({ ...weerinvoer(args), name: args.name || null, path,
        class_width: args.class_width, progress: voortgang(id) }));
    }
    case "trace_open": {
      const path = args.data ? bewaarReeks(args.name, args.data) : wisReeks();
      return toJs(web.trace_open.callKwargs({ path, name: args.name || null,
        pattern: args.pattern || "*" }));
    }
    case "trace":
      return toJs(web.trace.callKwargs({ name: args.name || null, path: reeksPad,
        options: py.toPy(args.options || {}), progress: voortgang(id) }));
    case "trace_apply":
      return toJs(web.trace_apply(args.level, args.sigma));
    case "export": {
      const data = toJs(web.export.callKwargs({ progress: voortgang(id) }));
      return data;
    }
    default:
      throw new Error("onbekende opdracht: " + cmd);
  }
}

onmessage = async (e) => {
  const { id, cmd, args } = e.data;
  try {
    const result = await call(cmd, args || {}, id);
    postMessage({ id, ok: true, result });
  } catch (err) {
    // een fout voor mensen, zoals het Windows-programma (stappen.readable_error); de ruwe tekst
    // gaat mee voor wie hem wil zien
    const technical = String(err && err.message || err);
    let error = technical;
    try { if (web) error = web.readable(technical); } catch (_) { /* dan de ruwe tekst */ }
    postMessage({ id, ok: false, error, technical });
  }
};
