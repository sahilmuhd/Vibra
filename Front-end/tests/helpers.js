// Loads the browser scripts (plain <script> files, no modules) into an
// isolated function scope with fake browser globals. No dependencies.
const fs = require('node:fs');
const path = require('node:path');

function makeStorage() {
  const m = new Map();
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    _dump: () => Object.fromEntries(m),
  };
}

// fetch mock: pass an array of handlers consumed in order, or a router fn.
function makeFetch(handler) {
  const calls = [];
  const fn = async (url, opts = {}) => {
    calls.push({ url, ...opts, body: opts.body ? JSON.parse(opts.body) : undefined });
    const r = await handler(url, opts, calls.length - 1);
    const status = r.status ?? 200;
    return { ok: status >= 200 && status < 300, status, json: async () => (r.json ?? {}) };
  };
  fn.calls = calls;
  return fn;
}

function loadApi({ fetch, hostname = 'localhost', config } = {}) {
  const localStorage = makeStorage();
  const window = {
    location: { hostname, protocol: 'http:' },
    __VIBRA_CONFIG__: config,
  };
  const src = fs.readFileSync(path.join(process.env.VIBRA_FRONTEND_DIR || path.join(__dirname, '..'), 'api.js'), 'utf8');
  const factory = new Function(
    'window', 'localStorage', 'fetch', 'WebSocket',
    `${src}\n;return { Api, API_BASE, VIBRA_CONFIG };`
  );
  class FakeWS { constructor(url) { FakeWS.last = url; } }
  const out = factory(window, localStorage, fetch, FakeWS);
  return { ...out, localStorage, window, FakeWS };
}

function loadApp({ api, demo = false } = {}) {
  const localStorage = makeStorage();
  const document = { addEventListener() {}, getElementById: () => null };
  const window = { location: { hostname: 'localhost' }, innerWidth: 1200 };
  const DATA = {
    users: [{ id: 'u1', name: 'Aisha', avatar: 'x' }], rooms: [{ id: 'r1', name: 'Mock', category: 'Talk', desc: '', online: 1, live: true }],
    getUser: () => undefined,
    avatarFor: (s) => `https://api.dicebear.com/7.x/notionists/svg?seed=${s}`,
    categories: ['All', 'Talk'],
    giftCatalog: [], packages: [],
  };
  const VIBRA_CONFIG = { DEMO_DATA: demo };
  const src = fs.readFileSync(path.join(process.env.VIBRA_FRONTEND_DIR || path.join(__dirname, '..'), 'app.js'), 'utf8');
  const names = [
    'escapeHTML', 'escapeAttr', 'safeImgUrl', 'parseRoomId', 'profileToAccount',
    'apiRoomToLocal', 'seatsFromDetail', 'getRooms', 'roomCardHTML', 'discoverRowHTML',
    'seatHTML', 'chatMessageHTML', 'STATE', 'ROOM_SEATS_CACHE',
  ];
  const factory = new Function(
    'document', 'window', 'localStorage', 'DATA', 'VIBRA_CONFIG', 'Api',
    `${src}\n;return { ${names.map((n) => `${n}: typeof ${n} === 'undefined' ? undefined : ${n}`).join(', ')} };`
  );
  return factory(document, window, localStorage, DATA, VIBRA_CONFIG, api || {});
}

module.exports = { loadApi, loadApp, makeFetch };
