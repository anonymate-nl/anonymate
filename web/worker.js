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
const PACKAGES = ["numpy", "pandas", "duckdb", "pyarrow", "h3", "micropip"];

let py = null;
let web = null;

const status = (text) => postMessage({ type: "status", text });

async function start(base) {
  status("Python laden (eenmalig ongeveer 30 MB)…");
  importScripts(PYODIDE + "pyodide.js");
  py = await loadPyodide({ indexURL: PYODIDE });
  status("Rekenbibliotheken laden: numpy, pandas, DuckDB, pyarrow, h3…");
  await py.loadPackage(PACKAGES);
  status("AnonyMate laden…");
  const info = await (await fetch(new URL("wheel.json", base))).json();
  const micropip = py.pyimport("micropip");
  // deps: false: alles wat nodig is, staat hierboven al; niets van PyPI halen
  await micropip.install.callKwargs(new URL(info.wheel, base).href, { deps: false });
  web = py.pyimport("anonymate.web");
  return { python: py.runPython("import sys; sys.version.split()[0]"),
           pyodide: py.version, anonymate: info.version };
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
  switch (cmd) {
    case "start":
      return start(args.base);
    case "open_practice":
      return toJs(web.open_practice());
    case "open_file": {
      // het bestand staat alleen in het geheugen van deze worker, en open_file ruimt het op
      py.FS.mkdirTree("/tmp/invoer");
      const path = "/tmp/invoer/" + args.name.replace(/[\\/]/g, "_");
      py.FS.writeFile(path, new Uint8Array(args.data));
      return toJs(web.open_file(path, args.name));
    }
    case "run":
      return toJs(web.run.callKwargs({
        mapping: py.toPy(args.mapping || {}), p: args.p, scenario: args.scenario,
      }));
    case "suggest": {
      const progress = (fraction, text) => postMessage({ type: "progress", fraction, text });
      return toJs(web.suggest.callKwargs({ target_share: 0.95, progress }));
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
    postMessage({ id, ok: false, error: String(err && err.message || err) });
  }
};
