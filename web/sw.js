// De service worker van AnonyMate: na het eerste bezoek werkt de pagina zonder internet.
//
// web/maak.py vult hieronder het bouw-id en de lijst van bestanden (met hun sha256) in, uit de
// inhoud van dist/; de lijst kan dus niet verouderen. Elk bestand wordt bij het binnenhalen
// gecontroleerd tegen die hash. De cache heet naar het bouw-id: een nieuwe versie krijgt een nieuwe
// cache, en de oude verdwijnt zodra de nieuwe actief wordt. Wat niet veranderd is (zelfde hash),
// neemt de nieuwe cache over van de oude, zonder het opnieuw te downloaden.
//
// De installatie (ruim 25 MB) start pas nadat de pagina is opgestart (app.js registreert dan),
// zodat het eerste gebruik er niet op wacht. Een nieuwe versie neemt de pagina niet zelf over
// midden in een beoordeling: hij wacht tot de gebruiker herlaadt (bericht "overnemen").

const BOUW = /*BOUW*/"";
const PRECACHE = /*PRECACHE*/{};
const VOORVOEGSEL = "anonymate-";
const NAAM = VOORVOEGSEL + BOUW;
const SCOPE = new URL("./", self.location.href);

const sleutel = (pad) => new URL(pad, SCOPE).href;

async function hex(buffer) {
  const digest = await crypto.subtle.digest("SHA-256", buffer);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

// haalt een bestand binnen (eerst zoals de browser dat zelf zou doen, dus vaak uit zijn eigen cache)
// en controleert de hash; klopt die niet, dan nog eens rechtstreeks van de server
async function binnenhalen(pad) {
  const verwacht = PRECACHE[pad];
  for (const cache of ["default", "reload"]) {
    const r = await fetch(sleutel(pad), { cache });
    if (!r.ok) throw new Error(`${pad}: ${r.status}`);
    const data = await r.arrayBuffer();
    if (verwacht === null || (await hex(data)) === verwacht) {
      return new Response(data, { status: 200, headers: r.headers });
    }
  }
  throw new Error(`${pad}: sha256 klopt niet`);
}

// hetzelfde bestand uit de cache van een eerdere versie, als de inhoud (sha256) gelijk is: een nieuwe
// versie verandert meestal alleen de wheel en de pagina, niet Pyodide (ruim 20 MB), en die hoeft dan
// niet opnieuw van de server te komen
async function uitEerdereVersie(pad) {
  const verwacht = PRECACHE[pad];
  if (!verwacht) return null;
  for (const naam of await caches.keys()) {
    if (!naam.startsWith(VOORVOEGSEL) || naam === NAAM) continue;
    const r = await (await caches.open(naam)).match(sleutel(pad));
    if (!r) continue;
    const data = await r.arrayBuffer();
    if ((await hex(data)) === verwacht) return new Response(data, { status: 200, headers: r.headers });
  }
  return null;
}

async function installeren() {
  const cache = await caches.open(NAAM);
  const paden = Object.keys(PRECACHE);
  let nu = 0;
  // een paar tegelijk: genoeg voor snelheid, zonder de pagina zelf te verdringen
  const werk = async () => {
    while (nu < paden.length) {
      const pad = paden[nu++];
      if (await cache.match(sleutel(pad))) continue;
      await cache.put(sleutel(pad), (await uitEerdereVersie(pad)) || (await binnenhalen(pad)));
    }
  };
  await Promise.all([werk(), werk(), werk()]);
}

async function opruimen() {
  for (const naam of await caches.keys()) {
    if (naam.startsWith(VOORVOEGSEL) && naam !== NAAM) await caches.delete(naam);
  }
}

// staat alles van deze versie in de cache?
async function compleet() {
  if (!(await caches.has(NAAM))) return false;
  const cache = await caches.open(NAAM);
  for (const pad of Object.keys(PRECACHE)) {
    if (!(await cache.match(sleutel(pad)))) return false;
  }
  return true;
}

self.addEventListener("install", (e) => e.waitUntil(installeren()));

self.addEventListener("activate", (e) => e.waitUntil((async () => {
  await opruimen();
  await self.clients.claim();
  const alle = await self.clients.matchAll();
  const klaar = await compleet();
  for (const c of alle) c.postMessage({ type: "offline", klaar, bouw: BOUW });
})()));

self.addEventListener("message", async (e) => {
  const m = e.data || {};
  if (m.type === "overnemen") self.skipWaiting();
  if (m.type === "status" && e.ports[0]) {
    e.ports[0].postMessage({ type: "offline", klaar: await compleet(), bouw: BOUW });
  }
});

// alles in de lijst komt uit de cache; wat er niet in staat (niets, als het goed is) gaat naar het netwerk
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== SCOPE.origin || !url.pathname.startsWith(SCOPE.pathname)) return;
  const pad = url.pathname.slice(SCOPE.pathname.length) || "index.html";
  if (!(pad in PRECACHE)) return;
  e.respondWith((async () => {
    const cache = await caches.open(NAAM);
    return (await cache.match(sleutel(pad))) || fetch(req);
  })());
});
