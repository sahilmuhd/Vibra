// End-to-end voice test: two real browsers (host + listener) talking through
// LiveKit, driven over the Chrome DevTools protocol (Node 22+, no dependencies).
//
// Needs real LIVEKIT_* values in Back-end/.env, then:
//   1. cd Back-end && venv/Scripts/daphne -b 127.0.0.1 -p 8000 config.asgi:application
//   2. cd Front-end && python -m http.server 5500 --bind 127.0.0.1
//   3. python tests/e2e/make_speech_wav.py speech.wav
//   4. chrome --headless=new --remote-debugging-port=9222 --user-data-dir=<tmp1>
//        --use-fake-ui-for-media-stream --use-fake-device-for-media-stream about:blank
//      chrome --headless=new --remote-debugging-port=9223 --user-data-dir=<tmp2>
//        --use-fake-ui-for-media-stream --use-fake-device-for-media-stream
//        --use-file-for-fake-audio-capture=<abs path>/speech.wav about:blank
//   5. node tests/e2e/voice.mjs        (GUEST_PORT overrides 9223)
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function page(port) {
  const list = await (await fetch(`http://127.0.0.1:${port}/json`)).json();
  const target = list.find((t) => t.type === 'page');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0;
  const pending = new Map();
  ws.onmessage = (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
  };
  const send = (method, params = {}) => new Promise((r) => {
    const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params }));
  });
  const evaluate = async (expr) => {
    const res = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true });
    if (res.result && res.result.exceptionDetails) {
      throw new Error(`${port}: ${res.result.exceptionDetails.exception?.description || res.result.exceptionDetails.text}`);
    }
    return res.result && res.result.result ? res.result.result.value : undefined;
  };
  await send('Runtime.enable');
  await send('Page.enable');
  return { send, evaluate, close: () => ws.close() };
}

const results = [];
const check = (name, ok, detail = '') => { results.push({ name, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + detail : ''}`); };

const host = await page(9222);
const guest = await page(Number(process.env.GUEST_PORT || 9223));
for (const p of [host, guest]) await p.send('Page.navigate', { url: 'http://localhost:5500/index.html' });
await sleep(6000);

const login = `(async()=>{ const p = await Api.guestLogin(); loginAs(profileToAccount(p)); return p.id; })()`;
const hostId = await host.evaluate(login);
const guestId = await guest.evaluate(login);
check('both users signed in', !!hostId && !!guestId, `host=${hostId} guest=${guestId}`);
await sleep(2000);

await host.evaluate(`createRoom('E2E voice test', 'automated', 'talk')`);
let roomId, hostVoice;
for (let i = 0; i < 20 && hostVoice !== 'connected'; i++) {
  await sleep(1000);
  roomId = await host.evaluate(`STATE.activeRoom && STATE.activeRoom.id`);
  hostVoice = await host.evaluate(`!!STATE.liveKitRoom && STATE.liveKitRoom.state`);
}
check('host created room and joined voice', typeof roomId === 'number' && hostVoice === 'connected', `room=${roomId} voice=${hostVoice}`);

await guest.evaluate(`openRoom(${roomId})`);
let guestVoice;
for (let i = 0; i < 25 && guestVoice !== 'connected'; i++) {
  await sleep(1000);
  guestVoice = await guest.evaluate(`!!STATE.liveKitRoom && STATE.liveKitRoom.state`);
}
const guestCanPublishBefore = await guest.evaluate(`STATE.liveKitRoom.localParticipant.permissions ? STATE.liveKitRoom.localParticipant.permissions.canPublish : null`);
check('listener joined voice without publish rights', guestVoice === 'connected' && guestCanPublishBefore === false, `voice=${guestVoice} canPublish=${guestCanPublishBefore}`);

// Listener takes seat 1 -> server must grant publish on the live connection.
await guest.evaluate(`requestSeat(1)`);
await sleep(8000);
const guestState = await guest.evaluate(`({
  canPublish: STATE.liveKitRoom.localParticipant.permissions && STATE.liveKitRoom.localParticipant.permissions.canPublish,
  micEnabled: STATE.liveKitRoom.localParticipant.isMicrophoneEnabled,
  seat: STATE.mySeatIndex,
})`);
check('taking a seat grants publish and turns the mic on', guestState.canPublish === true && guestState.micEnabled === true && guestState.seat === 1, JSON.stringify(guestState));

// Host should now receive the listener's audio and see them speaking.
let heard = null; let ringLit = false;
let maxLevel = 0;
for (let i = 0; i < 20 && !(heard && heard.subscribed && ringLit); i++) {
  heard = await host.evaluate(`(() => {
    const p = [...STATE.liveKitRoom.remoteParticipants.values()].find(p => p.identity === '${guestId}');
    if(!p) return null;
    const pubs = [...p.audioTrackPublications.values()];
    return { tracks: pubs.length, subscribed: pubs.some(t => t.isSubscribed), level: p.audioLevel, speaking: p.isSpeaking };
  })()`);
  if(heard) maxLevel = Math.max(maxLevel, heard.level || 0);
  ringLit = ringLit || await host.evaluate(`(() => { const r = document.querySelector('#mic-grid [data-seat-idx="1"] .vibra-ring'); return !!r && r.classList.contains('speaking'); })()`);
  await sleep(1000);
}
check('host receives the speaker\'s audio track', !!heard && heard.subscribed, JSON.stringify(heard));
check('speaking ring lights up from real audio', ringLit, `max audio level seen by host: ${maxLevel}`);

// Host force-mutes the speaker -> LiveKit revokes publish; self-unmute is refused.
await host.evaluate(`Api.forceMute(${roomId}, 1, true)`);
await sleep(5000);
const afterMute = await guest.evaluate(`({
  canPublish: STATE.liveKitRoom.localParticipant.permissions && STATE.liveKitRoom.localParticipant.permissions.canPublish,
  micOn: micOn,
})`);
check('host mute revokes publish on the server', afterMute.canPublish === false && afterMute.micOn === false, JSON.stringify(afterMute));
const unmute = await guest.evaluate(`Api.toggleMute(${roomId}, 1).then(() => 'allowed', e => e.message)`);
check('muted speaker cannot unmute themselves', unmute !== 'allowed', unmute);

// DM arrives live on the other user's personal socket.
await host.evaluate(`Api.sendDirectMessage(${guestId}, 'hello from the host')`);
await sleep(3000);
const badge = await guest.evaluate(`(() => { const b = document.querySelector('[data-nav="messages"] .nav-badge'); return b ? b.textContent + (b.classList.contains('show') ? ' shown' : ' hidden') : null; })()`);
check('DM shows up live as an unread badge', !!badge && badge.startsWith('1') && badge.endsWith('shown'), badge);

await host.evaluate(`Api.endRoom(${roomId})`);
await sleep(3000);
const guestAfterEnd = await guest.evaluate(`({ inRoom: !!STATE.activeRoom, voice: !!STATE.liveKitRoom })`);
check('ending the room disconnects the listener', !guestAfterEnd.inRoom && !guestAfterEnd.voice, JSON.stringify(guestAfterEnd));

host.close(); guest.close();
const failed = results.filter((r) => !r.ok).length;
console.log(`\n${results.length - failed}/${results.length} checks passed`);
process.exit(failed ? 1 : 0);
