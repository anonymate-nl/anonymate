// AnonyMate in de browser: de rekenkern in Pyodide, in een Web Worker.
//
// De pagina start deze worker vanuit een blob:-URL, zodat hij dezelfde Content-Security-Policy
// erft als de pagina (GitHub Pages kan geen headers meegeven; een worker van een gewone URL zou
// zonder policy draaien). Daarom zijn alle URL's hier absoluut: de pagina geeft zijn eigen adres
// mee in het eerste bericht.
//
// Berichten van de pagina: {id, cmd, args}. Antwoord: {id, ok, result} of {id, ok: false, error}.
// Tussendoor: {type: "status", text} en {type: "progress", fraction, text}.

const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/";
// h3 en pyarrow zijn er bij het opstarten niet bij: de oefenpopulatie komt kant-en-klaar als
// Parquet (DuckDB leest die zelf) en Parquet lezen gaat via DuckDB (kladbloknotitie 15, stap 1-2).
// h3 wordt pas geladen als een aanroep hem nodig blijkt te hebben (zie call).
const PACKAGES = ["numpy", "pandas", "duckdb"];
const POPULATIE = "/tmp/oefenpopulatie.parquet";

let py = null;
let web = null;
let populatieKlaar = false;

const status = (text) => postMessage({ type: "status", text });

// hoe lang elke fase van het opstarten duurt, in seconden (kladbloknotitie 15)
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

async function bytes(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return new Uint8Array(await r.arrayBuffer());
}

async function start(base) {
  mark = performance.now();
  status("Python en rekenbibliotheken laden (eenmalig ongeveer 20 MB)…");
  importScripts(PYODIDE + "pyodide.js");
  // de wheel en de oefenpopulatie komen binnen terwijl Python en de pakketten laden
  const wheel = timed("wheel_ophalen", (async () => {
    const info = await (await fetch(new URL("wheel.json", base))).json();
    return { info, data: await bytes(new URL(info.wheel, base)) };
  })());
  const populatie = timed("populatie_ophalen",
    bytes(new URL("oefenpopulatie.parquet", base)).catch(() => null));
  // wie de pagina alleen met de wheel host, krijgt de oefenpopulatie dan in het geheugen gemaakt
  wheel.catch(() => {});
  py = await loadPyodide({ indexURL: PYODIDE, packages: PACKAGES });
  lap("python_pakketten");
  status("AnonyMate uitpakken…");
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
  status("AnonyMate starten…");
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

async function call(cmd, args) {
  try {
    return await run(cmd, args);
  } catch (err) {
    // een functie die h3 nodig heeft (Weerlocatie, verzonnen plaatsen): nu pas laden, en opnieuw
    if (!/No module named 'h3'/.test(String(err && err.message || err))) throw err;
    status("h3 laden…");
    await py.loadPackage("h3");
    return run(cmd, args);
  }
}

// wat run en suggest van de pagina krijgen: de volledige mapping, de aanvaller en de afbakening
function invoer(args) {
  return {
    mapping: args.mapping ? py.toPy(args.mapping) : null,
    scenario: args.scenario ?? null,
    scope: args.scope ?? null,
  };
}

async function run(cmd, args) {
  switch (cmd) {
    case "start":
      return start(args.base);
    case "open_practice": {
      mark = performance.now();
      const out = toJs(populatieKlaar ? web.open_practice(POPULATIE) : web.open_practice());
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
      return toJs(web.run.callKwargs(invoer(args)));
    case "record":
      return toJs(web.record(args.index));
    case "suggest": {
      const progress = (fraction, text) => postMessage({ type: "progress", fraction, text });
      return toJs(web.suggest.callKwargs({ ...invoer(args), target_share: 0.95, progress }));
    }
    case "apply":
      return toJs(web.apply(args.step));
    case "export": {
      const data = toJs(web.export());
      return data;
    }
    default:
      throw new Error("onbekende opdracht: " + cmd);
  }
}

onmessage = async (e) => {
  const { id, cmd, args } = e.data;
  try {
    const result = await call(cmd, args || {});
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
