/* ============================================================================
   roomplus.js — phase 4 room features
   Room themes, host settings (announcement, welcome, slow mode, password),
   private-room password prompt, room levels and music playback.
   Uses app.js helpers at call time (ic, escapeHTML, showToast, STATE, Api ...).
   ============================================================================ */
const ROOM_THEMES = {
  '':       { name: 'Starry Night', note: 'Free' },
  rain:     { name: 'Midnight Rain' },
  beach:    { name: 'Sunset Beach' },
  neoncity: { name: 'Neon City' },
  sakura:   { name: 'Sakura Garden' },
  galaxy:   { name: 'Deep Galaxy' },
};
// Whitelisted so a server value can never inject a class name.
function roomThemeClass(key){ return key && ROOM_THEMES[key] ? `theme-${key}` : ''; }
const SLOW_MODES = [0, 5, 10, 30, 60];

/* ---------------------------------------------------------------- applying settings */
function applyRoomSettings(s, announce){
  const room = STATE.activeRoom;
  if(!room || !s) return;
  const before = { theme: room.theme || '', announcement: room.announcement || '', slowMode: room.slowMode || 0 };
  if(s.theme !== undefined) room.theme = s.theme || '';
  if(s.announcement !== undefined) room.announcement = s.announcement || '';
  if(s.welcome_message !== undefined) room.welcome = s.welcome_message || '';
  if(s.slow_mode !== undefined) room.slowMode = Number(s.slow_mode) || 0;
  if(s.has_password !== undefined) room.hasPassword = !!s.has_password;

  const screen = document.getElementById('screen-room');
  screen.classList.remove(...Object.keys(ROOM_THEMES).filter(Boolean).map(k => `theme-${k}`));
  const cls = roomThemeClass(room.theme);
  if(cls) screen.classList.add(cls);

  const bar = document.getElementById('room-announcement');
  bar.hidden = !room.announcement;
  document.getElementById('room-announcement-text').textContent = room.announcement || '';

  const slow = document.getElementById('room-slow-hint');
  slow.hidden = !room.slowMode;
  slow.textContent = room.slowMode ? `Slow mode · ${room.slowMode}s` : '';

  if(announce){
    if(before.theme !== room.theme) appendChatMessage({ system: true, text: `🎨 Room theme changed to ${(ROOM_THEMES[room.theme] || ROOM_THEMES['']).name}` });
    if(room.announcement && before.announcement !== room.announcement) appendChatMessage({ system: true, text: `📌 ${room.announcement}` });
    if(before.slowMode !== room.slowMode) appendChatMessage({ system: true, text: room.slowMode ? `🐢 Slow mode on: one message every ${room.slowMode}s` : 'Slow mode is off' });
  }
}
function updateRoomLevelChip(){
  const room = STATE.activeRoom, chip = document.getElementById('room-level');
  if(!chip) return;
  chip.hidden = !room || typeof room.id !== 'number';
  if(room) chip.querySelector('span').textContent = `Lv ${Number(room.level) || 1}`;
}
function clearRoomPlus(){
  const screen = document.getElementById('screen-room');
  screen.classList.remove(...Object.keys(ROOM_THEMES).filter(Boolean).map(k => `theme-${k}`));
  ['room-announcement', 'room-slow-hint'].forEach(id => { const el = document.getElementById(id); if(el) el.hidden = true; });
  Music.stop(true);
  showNowPlaying(null);
}

/* ---------------------------------------------------------------- host settings sheet */
let ownedThemes = new Set(['']);
async function openRoomSettings(){
  const room = STATE.activeRoom;
  if(!room) return;
  try{
    const items = await Api.getStore();
    ownedThemes = new Set(['', ...items.filter(i => i.kind === 'theme' && i.owned_until).map(i => i.key)]);
    STATE.themeItems = items.filter(i => i.kind === 'theme');
  }catch(e){ STATE.themeItems = STATE.themeItems || []; }
  STATE.pendingTheme = room.theme || '';
  renderThemePicker();
  document.getElementById('rs-announcement').value = room.announcement || '';
  document.getElementById('rs-welcome').value = room.welcome || '';
  document.getElementById('rs-slow').innerHTML = SLOW_MODES.map(s =>
    `<button type="button" class="chip ${s === (room.slowMode || 0) ? 'active' : ''}" data-slow="${s}">${s ? s + 's' : 'Off'}</button>`).join('');
  document.getElementById('rs-password').value = '';
  document.getElementById('rs-password-state').textContent = room.hasPassword ? 'This room has a password.' : 'Anyone can join.';
  document.getElementById('rs-password-clear').hidden = !room.hasPassword;
  openModal('room-settings-modal');
}
function renderThemePicker(){
  const keys = Object.keys(ROOM_THEMES);
  document.getElementById('rs-themes').innerHTML = keys.map(k => {
    const owned = ownedThemes.has(k);
    const item = (STATE.themeItems || []).find(i => i.key === k);
    return `<button type="button" class="theme-opt ${STATE.pendingTheme === k ? 'on' : ''} ${owned ? '' : 'locked'}" data-theme-pick="${escapeAttr(k)}">
      <span class="theme-swatch t-${k || 'starry'}">${owned ? '' : ic('lock')}</span>
      <span class="nm">${escapeHTML(ROOM_THEMES[k].name)}</span>
      <span class="pr">${owned ? (k ? 'Owned' : 'Free') : `${ic('coins')}${Number(item ? item.price : 0).toLocaleString()}`}</span>
    </button>`;
  }).join('');
}
async function saveRoomSettings(extra){
  const room = STATE.activeRoom;
  if(!room) return;
  const btn = document.getElementById('rs-save');
  btn.disabled = true;
  const body = Object.assign({
    theme: STATE.pendingTheme || '',
    announcement: document.getElementById('rs-announcement').value.trim(),
    welcome_message: document.getElementById('rs-welcome').value.trim(),
    slow_mode: Number((document.querySelector('#rs-slow .chip.active') || {}).dataset?.slow || 0),
  }, extra || {});
  const pw = document.getElementById('rs-password').value.trim();
  if(pw && !('password' in body)) body.password = pw;
  try{
    const s = await Api.updateRoomSettings(room.id, body);
    applyRoomSettings(s, false);
    closeModal('room-settings-modal');
    showToast('Room settings saved', 'success');
  }catch(e){ showToast(e.message || 'Could not save settings', 'error'); }
  finally{ btn.disabled = false; }
}

/* ---------------------------------------------------------------- private rooms: password prompt */
let pwResolve = null;
function promptRoomPassword(wrong){
  return new Promise(resolve => {
    pwResolve = resolve;
    const input = document.getElementById('room-pw-input');
    input.value = '';
    document.getElementById('room-pw-error').hidden = !wrong;
    openModal('room-password-modal');
    setTimeout(() => input.focus(), 250);
  });
}
function finishPasswordPrompt(value){
  closeModal('room-password-modal');
  if(pwResolve){ const r = pwResolve; pwResolve = null; r(value); }
}
// Joins, asking for the password when the server says the room is private.
async function joinRoomWithPassword(roomId){
  let password = null, wrong = false;
  for(;;){
    try{ return await Api.joinRoom(roomId, password); }
    catch(e){
      const code = e.data && e.data.code;
      if(code !== 'password_required' && code !== 'password_wrong') throw e;
      wrong = code === 'password_wrong';
      password = await promptRoomPassword(wrong);
      if(password == null){ const c = new Error(''); c.cancelled = true; throw c; }
    }
  }
}

/* ---------------------------------------------------------------- music */
const Music = {
  ctx: null, el: null, gain: null, monitor: null, dest: null, track: null, title: '', playing: false, url: null,
  canPlay(){
    const lk = STATE.liveKitRoom;
    return !!(lk && lk.localParticipant && lk.localParticipant.permissions && lk.localParticipant.permissions.canPublish);
  },
  async start(file){
    if(!canModerate()){ showToast('Only the host or a moderator can play music', 'info'); return; }
    if(!this.canPlay()){ showToast('Take a seat on the mic to play music', 'info'); return; }
    if(!/^audio\//.test(file.type) && !/\.(mp3|m4a|aac|wav|ogg|oga|flac|opus|webm)$/i.test(file.name)){ showToast('Choose an audio file', 'error'); return; }
    this.stop(true);
    try{
      const Ctx = window.AudioContext || window.webkitAudioContext;
      this.ctx = new Ctx();
      this.url = URL.createObjectURL(file);
      this.el = new Audio();
      this.el.src = this.url;
      this.el.crossOrigin = 'anonymous';
      const src = this.ctx.createMediaElementSource(this.el);
      this.gain = this.ctx.createGain();
      this.gain.gain.value = Number(document.getElementById('music-volume').value || 80) / 100;
      this.dest = this.ctx.createMediaStreamDestination();
      this.monitor = this.ctx.createGain();      // so the DJ hears it too
      this.monitor.gain.value = 0.6;
      src.connect(this.gain); this.gain.connect(this.dest); this.gain.connect(this.monitor); this.monitor.connect(this.ctx.destination);
      this.track = this.dest.stream.getAudioTracks()[0];
      const preset = LivekitClient.AudioPresets && (LivekitClient.AudioPresets.music || LivekitClient.AudioPresets.musicStereo);
      await STATE.liveKitRoom.localParticipant.publishTrack(this.track, Object.assign({
        name: 'music', source: LivekitClient.Track.Source.ScreenShareAudio, dtx: false, red: false,
      }, preset ? { audioPreset: preset } : {}));
      this.el.onended = () => this.stop();
      await this.ctx.resume();
      await this.el.play();
      this.title = file.name.replace(/\.[a-z0-9]+$/i, '').slice(0, 80);
      this.playing = true;
      this.announce();
      renderDjBar();
    }catch(e){
      console.error('music failed', e);
      showToast('Could not play that file', 'error');
      this.stop(true);
    }
  },
  toggle(){
    if(!this.el) return;
    if(this.el.paused){ this.ctx.resume(); this.el.play(); this.playing = true; }
    else { this.el.pause(); this.playing = false; }
    this.announce(); renderDjBar();
  },
  setVolume(v){ if(this.gain) this.gain.gain.value = v / 100; },
  stop(silent){
    const was = !!this.el;
    if(this.track && STATE.liveKitRoom){ try{ STATE.liveKitRoom.localParticipant.unpublishTrack(this.track); }catch(e){} }
    if(this.track){ try{ this.track.stop(); }catch(e){} }
    if(this.el){ this.el.pause(); this.el.removeAttribute('src'); }
    if(this.ctx){ this.ctx.close().catch(() => {}); }
    if(this.url) URL.revokeObjectURL(this.url);
    Object.assign(this, { ctx: null, el: null, gain: null, monitor: null, dest: null, track: null, playing: false, url: null });
    if(was && !silent){ this.announce(); }
    this.title = '';
    renderDjBar();
  },
  announce(){
    const sock = STATE.roomSocket;
    try{ if(sock && sock.readyState === 1) sock.send(JSON.stringify({ type: 'music', title: this.title, playing: this.playing && !!this.el })); }catch(e){}
  },
};
function renderDjBar(){
  const bar = document.getElementById('music-bar');
  if(!bar) return;
  if(Music.el){
    bar.hidden = false;
    bar.classList.add('dj');
    document.getElementById('music-title').textContent = Music.title || 'Music';
    document.getElementById('music-toggle').innerHTML = ic(Music.playing ? 'pause' : 'play');
    document.getElementById('music-stop').hidden = false;
    bar.classList.toggle('paused', !Music.playing);
  } else if(!STATE.nowPlaying){
    bar.hidden = true;
  }
}
// Listener side: someone else is playing music.
function showNowPlaying(info){
  STATE.nowPlaying = info && info.playing ? info : null;
  const bar = document.getElementById('music-bar');
  if(!bar || Music.el) return;
  if(!STATE.nowPlaying){ bar.hidden = true; return; }
  bar.hidden = false;
  bar.classList.remove('dj', 'paused');
  document.getElementById('music-title').textContent = info.title || 'Music';
  document.getElementById('music-toggle').innerHTML = ic(STATE.musicMuted ? 'volume-x' : 'volume-2');
  document.getElementById('music-stop').hidden = true;
}
function setListenerMusicVolume(v){
  document.querySelectorAll('audio.music-audio').forEach(a => { a.volume = v / 100; });
}

/* ---------------------------------------------------------------- bindings */
function bindRoomPlus(){
  document.getElementById('rs-themes').addEventListener('click', e => {
    const b = e.target.closest('[data-theme-pick]'); if(!b) return;
    const k = b.dataset.themePick;
    if(!ownedThemes.has(k)){ closeModal('room-settings-modal'); openStore('theme'); return; }
    STATE.pendingTheme = k; renderThemePicker();
  });
  document.getElementById('rs-slow').addEventListener('click', e => {
    const b = e.target.closest('[data-slow]'); if(!b) return;
    document.querySelectorAll('#rs-slow .chip').forEach(c => c.classList.toggle('active', c === b));
  });
  document.getElementById('rs-save').addEventListener('click', () => saveRoomSettings());
  document.getElementById('rs-password-clear').addEventListener('click', () => saveRoomSettings({ password: '' }));
  document.getElementById('room-pw-form').addEventListener('submit', e => {
    e.preventDefault();
    const v = document.getElementById('room-pw-input').value.trim();
    if(v) finishPasswordPrompt(v);
  });
  document.getElementById('room-pw-cancel').addEventListener('click', () => finishPasswordPrompt(null));
  document.getElementById('room-password-modal').addEventListener('click', e => { if(e.target.id === 'room-password-modal') finishPasswordPrompt(null); });
  document.getElementById('music-file').addEventListener('change', e => {
    const f = e.target.files && e.target.files[0];
    e.target.value = '';
    if(f) Music.start(f);
  });
  document.getElementById('music-toggle').addEventListener('click', () => {
    if(Music.el) return Music.toggle();
    STATE.musicMuted = !STATE.musicMuted;
    document.querySelectorAll('audio.music-audio').forEach(a => { a.muted = STATE.musicMuted || !speakerOn; });
    showNowPlaying(STATE.nowPlaying);
  });
  document.getElementById('music-stop').addEventListener('click', () => Music.stop());
  document.getElementById('music-volume').addEventListener('input', e => {
    const v = Number(e.target.value);
    if(Music.el) Music.setVolume(v); else setListenerMusicVolume(v);
  });
  document.getElementById('room-announcement').addEventListener('click', () => {
    document.getElementById('room-announcement').classList.toggle('open');
  });
}
