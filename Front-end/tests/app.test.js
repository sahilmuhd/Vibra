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
  assert.deepEqual(a, { id: 9, name: 'sahil', username: 'sahil', avatar: 'https://x/y.svg', level: 2, bio: 'hi', country: 'IN', followers: 3, following: 4 });
});

test('parseRoomId: digits become numbers (API rooms), others stay strings (demo rooms)', () => {
  const { parseRoomId } = loadApp();
  assert.equal(parseRoomId('42'), 42);
  assert.equal(parseRoomId('r17'), 'r17');
});
