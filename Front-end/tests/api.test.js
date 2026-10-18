const test = require('node:test');
const assert = require('node:assert/strict');
const { loadApi, makeFetch } = require('./helpers');

const TOKENS = { access: 'ACC1', refresh: 'REF1' };

test('API base defaults: localhost in dev, Render in production, overridable', () => {
  assert.equal(loadApi({ fetch: makeFetch(() => ({})), hostname: 'localhost' }).API_BASE, 'http://localhost:8000/api');
  assert.equal(loadApi({ fetch: makeFetch(() => ({})), hostname: 'vibra.example.com' }).API_BASE, 'https://vibra-backend-vac1.onrender.com/api');
  const o = loadApi({ fetch: makeFetch(() => ({})), config: { API_BASE: 'https://api.test/api', DEMO_DATA: true } });
  assert.equal(o.API_BASE, 'https://api.test/api');
  assert.equal(o.VIBRA_CONFIG.DEMO_DATA, true);
  assert.equal(loadApi({ fetch: makeFetch(() => ({})) }).VIBRA_CONFIG.DEMO_DATA, false, 'demo data must default OFF');
});

test('login stores tokens, then loads /me', async () => {
  const fetch = makeFetch((url) => url.endsWith('/auth/login/') ? { json: TOKENS } : { json: { id: 7, username: 'sahil' } });
  const { Api, localStorage } = loadApi({ fetch });
  const me = await Api.login({ username: 'Sahil', password: 'pw' });
  assert.equal(me.id, 7);
  assert.equal(localStorage.getItem('vibra_access'), 'ACC1');
  assert.equal(localStorage.getItem('vibra_refresh'), 'REF1');
  assert.deepEqual(fetch.calls[0].body, { username: 'Sahil', password: 'pw' });
  assert.equal(fetch.calls[1].headers.Authorization, 'Bearer ACC1');
});

test('signup does NOT create a session (UI sends user to login)', async () => {
  const fetch = makeFetch(() => ({ status: 201, json: { user: { id: 1 }, ...TOKENS } }));
  const { Api, localStorage } = loadApi({ fetch });
  await Api.signup({ name: 'n', username: 'u', email: 'e@e.co', password: 'p', dob: '2000-01-01' });
  assert.equal(localStorage.getItem('vibra_access'), null);
  assert.equal(Api.hasSession(), false);
});

test('401 -> refresh -> retry succeeds transparently', async () => {
  let n = 0;
  const fetch = makeFetch((url) => {
    if (url.endsWith('/auth/login/refresh/')) return { json: { access: 'ACC2' } };
    return ++n === 1 ? { status: 401, json: { detail: 'expired' } } : { json: { ok: true } };
  });
  const { Api, localStorage } = loadApi({ fetch });
  Api.setTokens('OLD', 'REF1');
  const out = await Api.request('/rooms/');
  assert.deepEqual(out, { ok: true });
  assert.equal(localStorage.getItem('vibra_access'), 'ACC2');
  assert.equal(fetch.calls.at(-1).headers.Authorization, 'Bearer ACC2');
});

test('concurrent 401s share a single refresh call', async () => {
  let refreshCalls = 0;
  const seen = new Set();
  const fetch = makeFetch(async (url, opts) => {
    if (url.endsWith('/auth/login/refresh/')) { refreshCalls++; await new Promise((r) => setTimeout(r, 20)); return { json: { access: 'NEW' } }; }
    const key = url + opts.headers.Authorization;
    if (opts.headers.Authorization === 'Bearer OLD') return { status: 401, json: {} };
    seen.add(key); return { json: { ok: 1 } };
  });
  const { Api } = loadApi({ fetch });
  Api.setTokens('OLD', 'REF1');
  await Promise.all([Api.request('/a/'), Api.request('/b/'), Api.request('/c/')]);
  assert.equal(refreshCalls, 1);
});

test('failed refresh clears tokens, fires onAuthLost once, and throws', async () => {
  const fetch = makeFetch((url) => url.endsWith('/auth/login/refresh/') ? { status: 401, json: {} } : { status: 401, json: { detail: 'bad token' } });
  const { Api, localStorage } = loadApi({ fetch });
  let lost = 0; Api.onAuthLost = () => lost++;
  Api.setTokens('OLD', 'DEAD');
  await assert.rejects(Api.request('/rooms/'), (e) => e.status === 401 && /bad token/.test(e.message));
  assert.equal(lost, 1);
  assert.equal(localStorage.getItem('vibra_access'), null);
  assert.equal(localStorage.getItem('vibra_refresh'), null);
});

test('wrong password (401 on unauthenticated login) does not trigger refresh or onAuthLost', async () => {
  const fetch = makeFetch(() => ({ status: 401, json: { detail: 'No active account found with the given credentials' } }));
  const { Api } = loadApi({ fetch });
  let lost = 0; Api.onAuthLost = () => lost++;
  await assert.rejects(Api.login({ username: 'x', password: 'y' }), /No active account/);
  assert.equal(lost, 0);
  assert.equal(fetch.calls.length, 1);
});

test('network failure becomes a friendly error with status 0', async () => {
  const fetch = async () => { throw new TypeError('Failed to fetch'); };
  const { Api } = loadApi({ fetch });
  await assert.rejects(Api.request('/rooms/'), (e) => e.status === 0 && /reach the Vibra server/.test(e.message));
});

test('validation errors surface the first field message', async () => {
  const fetch = makeFetch(() => ({ status: 400, json: { username: ['Username already taken.'] } }));
  const { Api } = loadApi({ fetch });
  await assert.rejects(Api.request('/auth/signup/', { method: 'POST', auth: false, body: {} }), /Username already taken\./);
});

test('REGRESSION: password reset calls work (previously threw: this._req is not a function)', async () => {
  const fetch = makeFetch(() => ({ json: { detail: 'ok' } }));
  const { Api } = loadApi({ fetch });
  await Api.requestPasswordReset('a@b.co');
  await Api.resetPassword('tok', 'NewPass-123');
  assert.match(fetch.calls[0].url, /\/auth\/password-reset\/$/);
  assert.deepEqual(fetch.calls[0].body, { email: 'a@b.co' });
  assert.match(fetch.calls[1].url, /\/auth\/password-reset\/confirm\/$/);
  assert.deepEqual(fetch.calls[1].body, { token: 'tok', new_password: 'NewPass-123' });
  assert.equal(fetch.calls[1].headers.Authorization, undefined, 'reset must not send a stale bearer token');
});

test('join / leave / list endpoints', async () => {
  const fetch = makeFetch(() => ({ json: {} }));
  const { Api } = loadApi({ fetch });
  Api.setTokens('A', 'R');
  await Api.joinRoom(5); await Api.leaveRoom(5); await Api.listRooms(); await Api.listRooms('Music'); await Api.listRooms('All');
  const urls = fetch.calls.map((c) => `${c.method} ${c.url.replace('http://localhost:8000/api', '')}`);
  assert.deepEqual(urls, ['POST /rooms/5/join/', 'POST /rooms/5/leave/', 'GET /rooms/', 'GET /rooms/?category=music', 'GET /rooms/']);
});

test('leaveRoomOnExit uses keepalive, no retry, and never throws', async () => {
  const fetch = makeFetch(() => ({ status: 401, json: {} }));
  const { Api } = loadApi({ fetch });
  Api.setTokens('A', 'R');
  await Api.leaveRoomOnExit(9);
  assert.equal(fetch.calls.length, 1, 'no refresh round-trip while the page is unloading');
  assert.equal(fetch.calls[0].keepalive, true);
});

test('websocket URL: ws/wss scheme, /api stripped, token URL-encoded', () => {
  const dev = loadApi({ fetch: makeFetch(() => ({})) });
  dev.Api.setTokens('a.b+c/d=', 'r');
  assert.equal(dev.Api.wsUrl(3), 'ws://localhost:8000/ws/rooms/3/?token=a.b%2Bc%2Fd%3D');
  const prod = loadApi({ fetch: makeFetch(() => ({})), hostname: 'vibra.example.com' });
  assert.match(prod.Api.wsUrl(3), /^wss:\/\/vibra-backend-vac1\.onrender\.com\/ws\/rooms\/3\/\?token=/);
  dev.Api.connectRoomSocket(3, () => {});
  assert.match(dev.FakeWS.last, /^ws:\/\/localhost:8000\/ws\/rooms\/3\//);
});

test('logout clears both tokens', () => {
  const { Api, localStorage } = loadApi({ fetch: makeFetch(() => ({})) });
  Api.setTokens('A', 'R'); Api.logout();
  assert.equal(localStorage.getItem('vibra_access'), null);
  assert.equal(localStorage.getItem('vibra_refresh'), null);
  assert.equal(Api.hasSession(), false);
});
