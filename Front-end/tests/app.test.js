const test = require('node:test');
const assert = require('node:assert/strict');
const { loadApp } = require('./helpers');

const EVIL = '<img src=x onerror=alert(1)>"\'';

test('escapeHTML neutralises tags, quotes and null', () => {
  const { escapeHTML } = loadApp();
  assert.equal(escapeHTML(EVIL), '&lt;img src=x onerror=alert(1)&gt;&quot;&#39;');
  assert.equal(escapeHTML(null), '');
  assert.equal(escapeHTML(0), '0');
});

test('safeImgUrl only allows http(s)', () => {
  const { safeImgUrl } = loadApp();
  assert.equal(safeImgUrl('https://api.dicebear.com/x.svg'), 'https://api.dicebear.com/x.svg');
  for (const bad of ['javascript:alert(1)', 'data:text/html,<script>', 'vbscript:x', '']) assert.equal(safeImgUrl(bad), '', bad);
});

test('XSS: room card escapes server-supplied name/desc/category/id/host avatar', () => {
  const app = loadApp();
  const room = app.apiRoomToLocal({
    id: 5, name: EVIL, description: EVIL, category: EVIL, online_count: 2, is_live: true,
    host: { id: 1, username: EVIL, avatar_url: 'https://x.com/a"onerror="alert(1)', level: 1 },
  });
  for (const html of [app.roomCardHTML(room), app.discoverRowHTML(room)]) {
    assert.ok(!/<img src=x/i.test(html), 'raw injected tag present');
    assert.ok(!/onerror="alert/.test(html), 'attribute breakout present');
    assert.ok(html.includes('&lt;img src=x'));
  }
});

test('XSS: seats and chat messages escape usernames and avatar URLs', () => {
  const app = loadApp();
  app.STATE.currentUser = { id: 1, username: 'me' };
  app.STATE.activeRoom = { id: 5 };
  app.ROOM_SEATS_CACHE[5] = [];
  const seat = app.seatsFromDetail({ seats: [{ is_muted: false, user: { id: 2, username: EVIL, level: 3, avatar_url: 'javascript:alert(1)' } }] })[0];
  const sh = app.seatHTML(seat, 0);
  assert.ok(!/<img src=x/i.test(sh));
  assert.ok(!/src="javascript:/.test(sh));
  const ch = app.chatMessageHTML({ who: 'x', text: EVIL, displayName: EVIL, avatarUrl: 'https://x.com/"onerror="1', time: '1:00' });
  assert.ok(!/<img src=x/i.test(ch));
  assert.ok(!/onerror="1/.test(ch));
});

test('seatsFromDetail identifies "me" by numeric id, not username', () => {
  const app = loadApp();
  app.STATE.currentUser = { id: 7, username: 'alice' };
  const seats = app.seatsFromDetail({ seats: [
    { is_muted: true, user: { id: 7, username: 'someone_else_now_named_alice', level: 1, avatar_url: '' } },
    { is_muted: true, user: { id: 8, username: 'alice', level: 1, avatar_url: '' } },
    { is_muted: true, user: null },
  ] });
  assert.equal(seats[0].isMe, true);
  assert.equal(seats[1].isMe, false);
  assert.deepEqual(seats[2], { empty: true });
});

test('real mode shows ONLY backend rooms; DEMO_DATA adds the mock ones', () => {
  const real = loadApp({ demo: false });
  real.STATE.apiRooms = [{ id: 1, name: 'API room' }];
  assert.deepEqual(real.getRooms().map((r) => r.id), [1]);
  const demo = loadApp({ demo: true });
  demo.STATE.apiRooms = [{ id: 1, name: 'API room' }];
  assert.ok(demo.getRooms().length >= 1);
});

test('profileToAccount maps /me payload incl. id and counts', () => {
  const { profileToAccount } = loadApp();
  const a = profileToAccount({ id: 9, username: 'sahil', avatar_url: 'https://x/y.svg', level: 2, bio: 'hi', country: 'IN', followers_count: 3, following_count: 4 });
  assert.deepEqual(a, { id: 9, name: 'sahil', username: 'sahil', avatar: 'https://x/y.svg', level: 2, bio: 'hi', country: 'IN', followers: 3, following: 4,
    wealth_level: 2, charm_level: 1, vip: 0, frame: '', mount: '', is_admin: false,
    family: null, family_tag: '', cp: null, new_visitors: 0 });
});

test('status fields map from /me and render on seats without perks.js', () => {
  const app = loadApp();
  const a = app.profileToAccount({ id: 1, username: 'v', level: 5, wealth: { level: 5 }, charm: { level: 3 }, vip: { tier: 2 }, frame: 'gold', mount: 'car' });
  assert.equal(a.vip, 2); assert.equal(a.charm_level, 3); assert.equal(a.frame, 'gold'); assert.equal(a.mount, 'car');
  app.STATE.currentUser = { id: 1 }; app.STATE.activeRoom = { id: 5 }; app.ROOM_SEATS_CACHE[5] = [];
  const seat = app.seatsFromDetail({ seats: [{ is_muted: false, user: { id: 2, username: 'x', level: 3, avatar_url: '', frame: '"><script>', vip: 4 } }] })[0];
  assert.ok(!/<script>/.test(app.seatHTML(seat, 0)));
});

test('room list row escapes and shows lock/level from the API', () => {
  const app = loadApp();
  const room = app.apiRoomToLocal({ id: 3, name: 'x', description: '', category: 'talk', online_count: 1, is_live: true,
    has_password: true, level: 6, theme: '"><script>', host: { id: 1, username: 'h', avatar_url: '', level: 1 } });
  const html = app.roomCardHTML(room, 0);
  assert.ok(html.includes('rr-lock'));
  assert.ok(html.includes('Lv 6'));
  assert.ok(!/<script>/.test(html));
});

test('chat messages: unknown sticker keys and voice without social.js stay plain, escaped text', () => {
  const app = loadApp();
  app.STATE.activeRoom = { id: 5 };
  const html = app.chatMessageHTML({ who: 'x', displayName: 'x', avatarUrl: 'https://x.com/a.png', text: '[sticker:<img src=x>]', time: '1:00', voice: { url: 'javascript:alert(1)', seconds: 3 } });
  assert.ok(!/<img src=x/.test(html));
  assert.ok(!/javascript:/.test(html));
});

test('parseRoomId: digits become numbers (API rooms), others stay strings (demo rooms)', () => {
  const { parseRoomId } = loadApp();
  assert.equal(parseRoomId('42'), 42);
  assert.equal(parseRoomId('r17'), 'r17');
});
