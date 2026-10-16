/* ==========================================================================
   VIBRA — APPLICATION LOGIC
   Organized into clearly separated modules so it can be lifted into React:
   STATE -> STORAGE -> TOAST -> NAV -> AUTH -> HOME/ROOMS -> CHAT -> WALLET ->
   PROFILE -> MESSAGES -> NOTIFICATIONS -> CREATE ROOM -> SETTINGS -> INIT
   ========================================================================== */

/* ---------------------------- STATE (app.js) ---------------------------- */
const STATE = {
  currentUser: null,
  activeRoom: null,
  activeCategory: 'All',
  activeDM: null,
  giftRecipient: null,
  giftSeatIdx: null,
  selectedGift: null,
  txHistoryOpen: false,
  // room-interaction state
  isHost: false,
  mySeatIndex: -1,
  seatsLocked: false,
  handRaised: false,
  handQueue: [],       // simulated other users requesting mic: {name, avatar, level}
  replyTo: null,       // {name, text}
  lastGiftKey: null,
  lastGiftTime: 0,
  giftCombo: 1,
  roomTimers: [],       // interval ids for the currently open room
  apiRooms: [],         // rooms fetched from the real backend (Api.listRooms)
  roomSocket: null,     // active WebSocket for the currently open API room
  liveKitRoom: null,    // active LiveKit Room instance (real voice) for the currently open API room
};

// per-session cache so reopening the same room keeps seat state instead of re-randomizing
const ROOM_SEATS_CACHE = {};

/* ---------------------------- STORAGE (data.js) -------------------------- */
const Storage = {
  KEYS: {
    USER: 'vibra_current_user',
    ACCOUNTS: 'vibra_accounts',
    WALLET: 'vibra_wallet',
    TX: 'vibra_transactions',
    ROOMS: 'vibra_rooms',
    FOLLOWING: 'vibra_following',
    GIFT_HISTORY: 'vibra_gift_history',
    NOTIFS: 'vibra_notifs_read',
  },
  get(key, fallback){
    try{
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    }catch(e){ return fallback; }
  },
  set(key, val){
    try{ localStorage.setItem(key, JSON.stringify(val)); }catch(e){ /* storage unavailable */ }
  }
};

function initStorageDefaults(){
  if(!Storage.get(Storage.KEYS.ACCOUNTS)) Storage.set(Storage.KEYS.ACCOUNTS, []);
  if(Storage.get(Storage.KEYS.WALLET) === null) Storage.set(Storage.KEYS.WALLET, 12500);
  if(!Storage.get(Storage.KEYS.TX)) Storage.set(Storage.KEYS.TX, [
    {id:'t1', type:'received', label:'Gift from Aisha', time:'2 hours ago', amount:50, positive:true},
    {id:'t2', type:'purchase', label:'Purchased 500 Coins', time:'Yesterday', amount:500, positive:true},
    {id:'t3', type:'sent', label:'Sent Crown to Rahul', time:'2 days ago', amount:-500, positive:false},
  ]);
  if(!Storage.get(Storage.KEYS.ROOMS)) Storage.set(Storage.KEYS.ROOMS, DATA.rooms);
  if(!Storage.get(Storage.KEYS.FOLLOWING)) Storage.set(Storage.KEYS.FOLLOWING, []);
  if(!Storage.get(Storage.KEYS.GIFT_HISTORY)) Storage.set(Storage.KEYS.GIFT_HISTORY, []);
}

function getRooms(){ return [...STATE.apiRooms, ...Storage.get(Storage.KEYS.ROOMS, DATA.rooms)]; }

/* ---- real backend rooms (Api.listRooms) — kept separate from the mock
   DATA.rooms array and merged in by getRooms() above ---- */
const ROOM_GRADIENTS = [
  'linear-gradient(135deg,#7b2ff7,#f107a3)',
  'linear-gradient(135deg,#0ea5e9,#7c3aed)',
  'linear-gradient(135deg,#f43f5e,#f97316)',
  'linear-gradient(135deg,#10b981,#0ea5e9)',
];
function apiRoomToLocal(r){
  return {
    id: r.id, // numeric — this is how we tell an API room apart from a mock 'r...' room
    name: r.name,
    desc: r.description || '',
    category: r.category,
    online: r.online_count || 0,
    live: r.is_live,
    grad: ROOM_GRADIENTS[r.id % ROOM_GRADIENTS.length],
    hostId: r.host ? r.host.id : null,
    hostDisplay: r.host ? { name: r.host.username, username: r.host.username, avatar: r.host.avatar_url, level: r.host.level } : null,
  };
}
async function refreshApiRooms(){
  try{
    const rooms = await Api.listRooms();
    STATE.apiRooms = rooms.map(apiRoomToLocal);
  }catch(e){
    console.error('Could not load rooms from server', e);
  }
}
function getWallet(){ return Storage.get(Storage.KEYS.WALLET, 0); }
function setWallet(v){ Storage.set(Storage.KEYS.WALLET, Math.max(0, v)); }

/* ---------------------------- TOAST (app.js) ----------------------------- */
// Deterministic "random" based on a string seed — used so decorative values
// (who's ring is pulsing, gift counts shown) don't reshuffle every re-render.
function seededRandom(seed){
  let h = 0;
  for(let i=0;i<seed.length;i++){ h = (h*31 + seed.charCodeAt(i)) | 0; }
  return Math.abs(Math.sin(h)) % 1;
}

function showToast(message, type){
  type = type || 'info';
  const stack = document.getElementById('toast-stack');
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icon = type==='success' ? '✅' : type==='error' ? '⚠️' : '💬';
  el.innerHTML = `<span>${icon}</span><span>${message}</span>`;
  stack.appendChild(el);
  setTimeout(()=> el.remove(), 3000);
}

/* ---------------------------- NAVIGATION (navigation.js) ----------------- */
function navigateTo(tabName){
  document.querySelectorAll('.app-tab').forEach(t=> t.classList.add('hidden'));
  const target = document.getElementById('tab-'+tabName);
  if(target) target.classList.remove('hidden');

  document.querySelectorAll('.nav-item[data-nav]').forEach(n=>{
    n.classList.toggle('active', n.dataset.nav === tabName);
  });
  document.querySelectorAll('.side-link[data-nav]').forEach(n=>{
    n.classList.toggle('active', n.dataset.nav === tabName);
  });

  if(tabName === 'create'){
    openOverlay('screen-create-room');
    navigateTo('home');
    return;
  }
  if(tabName === 'profile'){
    renderOwnProfile();
  }
  if(tabName === 'messages'){
    renderMessagesList();
  }
  window.scrollTo(0,0);
}

function openOverlay(id){
  const el = document.getElementById(id);
  el.classList.remove('closing');
  el.classList.add('active');
  document.body.style.overflow = 'hidden';
}
function closeOverlay(id){
  const el = document.getElementById(id);
  if(!el || !el.classList.contains('active')) return;
  el.classList.add('closing');
  setTimeout(()=>{
    el.classList.remove('active');
    el.classList.remove('closing');
    document.body.style.overflow = '';
  }, 180);
}
function openModal(id){
  const el = document.getElementById(id);
  el.classList.remove('closing');
  el.classList.add('show');
}
function closeModal(id){
  const el = document.getElementById(id);
  if(!el || !el.classList.contains('show')) return;
  el.classList.add('closing');
  setTimeout(()=>{
    el.classList.remove('show');
    el.classList.remove('closing');
  }, 180);
}

/* ---------------------------- AUTH (auth.js) ------------------------------ */
function switchAuthScreen(show, hide){
  document.getElementById(hide).classList.add('hidden');
  document.getElementById(show).classList.remove('hidden');
}

function setFieldError(fieldId, isError){
  const el = document.getElementById(fieldId);
  if(el) el.classList.toggle('error', isError);
}

function validateLogin(){
  let ok = true;
  const id = document.getElementById('login-id').value.trim();
  const pw = document.getElementById('login-pw').value;
  setFieldError('login-id-field', !id); if(!id) ok=false;
  setFieldError('login-pw-field', !pw); if(!pw) ok=false;
  return ok;
}

async function doLogin(identifier, password){
  try{
    const profile = await Api.login({ username: identifier, password });
    loginAs({
      name: profile.username, username: profile.username,
      email: identifier.includes('@') ? identifier : '',
      avatar: profile.avatar_url || DATA.avatarFor(profile.username),
      level: profile.level,
    });
  }catch(e){
    showToast(e.message || 'Login failed', 'error');
  }
}

function loginAs(account){
  STATE.currentUser = account;
  Storage.set(Storage.KEYS.USER, account);
  enterApp();
  showToast(`Welcome back, ${account.name.split(' ')[0]}!`, 'success');
}

async function doSignup(data){
  try{
    await Api.signup({
      name: data.name, username: data.username,
      email: data.email, password: data.password, dob: data.dob,
    });
    switchAuthScreen('screen-login', 'screen-signup');
    document.getElementById('login-success').classList.add('show');
    document.getElementById('login-id').value = data.username;
  }catch(e){
    showToast(e.message || 'Signup failed', 'error');
  }
}

function enterApp(){
  document.getElementById('screen-login').classList.add('hidden');
  document.getElementById('screen-signup').classList.add('hidden');
  document.getElementById('app-shell').classList.add('active');
  const u = STATE.currentUser;
  document.getElementById('mini-avatar').src = u.avatar;
  const hour = new Date().getHours();
  const g = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
  document.getElementById('home-greeting').innerHTML = `${g}, ${u.name.split(' ')[0]}<span>Welcome back to Vibra</span>`;
  if(window.innerWidth >= 1080){ document.getElementById('desktop-sidebar').style.display='flex'; document.getElementById('desktop-right').style.display='block'; }
  refreshApiRooms().then(renderHome);
  renderHome();
  navigateTo('home');
}

/* ---------------------------- HOME / ROOMS (home.js, rooms.js) ----------- */
function renderStories(){
  const row = document.getElementById('stories-row');
  let html = `<div class="story story-add"><div class="avatar-frame">+</div><span>Add Story</span></div>`;
  DATA.users.filter(u=>u.online).forEach(u=>{
    html += `<div class="story" data-open-profile="${u.id}">
      <div class="vibra-ring ${seededRandom(u.id+'story')>0.6?'speaking':''}"><img class="avatar" src="${u.avatar}"><span class="online-dot"></span></div>
      <span>${u.name.split(' ')[0]}</span>
    </div>`;
  });
  row.innerHTML = html;
}

function renderCategories(){
  const row = document.getElementById('category-row');
  row.innerHTML = DATA.categories.map(c =>
    `<button class="chip ${c===STATE.activeCategory?'active':''}" data-cat="${c}">${c}</button>`
  ).join('');
}

function filteredRooms(searchTerm){
  let rooms = getRooms();
  if(STATE.activeCategory && STATE.activeCategory !== 'All'){
    if(STATE.activeCategory === 'Trending'){
      rooms = rooms.filter(r=> r.online > 1000);
    } else {
      rooms = rooms.filter(r=> r.category === STATE.activeCategory);
    }
  }
  if(searchTerm){
    const q = searchTerm.toLowerCase();
    rooms = rooms.filter(r=> r.name.toLowerCase().includes(q) || r.desc.toLowerCase().includes(q) || r.category.toLowerCase().includes(q));
  }
  return rooms;
}

function roomCardHTML(room){
  const host = DATA.getUser(room.hostId);
  const avatars = DATA.users.slice(0,3).map(u=>`<img class="avatar" src="${u.avatar}">`).join('');
  return `
  <div class="room-card" data-room-id="${room.id}" style="--rgrad:${room.grad}">
    <div style="position:absolute; inset:0; background:${room.grad}; opacity:0.9; z-index:0;"></div>
    <div class="room-card-top">
      <span class="room-badge ${room.live?'live':''}">${room.live? '🔴 LIVE' : '⏸ OFFLINE'}</span>
      <span class="room-cat">${room.category}</span>
    </div>
    <div class="room-name">${room.name}</div>
    <div class="room-desc">${room.desc}</div>
    <div class="room-card-bottom">
      <div style="display:flex; align-items:center;">
        <div class="room-avatars">${avatars}</div>
        <span class="room-online">${room.online.toLocaleString()} online</span>
      </div>
      <button class="room-join" data-join-room="${room.id}">Join</button>
    </div>
  </div>`;
}

function renderTrendingRooms(){
  const rooms = [...getRooms()].sort((a,b)=> b.online - a.online).slice(0,6);
  const el = document.getElementById('trending-rooms');
  el.innerHTML = rooms.length ? rooms.map(roomCardHTML).join('') : emptyStateHTML('🔍','No rooms found','Try a different category or search term.');
}

function discoverRowHTML(room){
  const host = DATA.getUser(room.hostId) || room.hostDisplay;
  return `<div class="discover-row" data-room-id="${room.id}">
    <div class="thumb" style="background:${room.grad};"></div>
    <div class="meta">
      <div class="name">${room.name}</div>
      <div class="sub">${host? host.name : 'Vibra'} · ${room.online.toLocaleString()} online · ${room.category}</div>
    </div>
    <button class="join-mini btn-glass" data-join-room="${room.id}">Join</button>
  </div>`;
}

function renderRecommended(){
  const rooms = filteredRooms(document.getElementById('room-search').value).slice(0,4);
  document.getElementById('recommended-rooms').innerHTML = rooms.length ? rooms.map(discoverRowHTML).join('') : emptyStateHTML('✨','Nothing here yet','Follow more people to get better recommendations.');
}

function emptyStateHTML(emoji, title, sub){
  return `<div class="empty-state"><div class="emoji">${emoji}</div><h3>${title}</h3><p>${sub}</p></div>`;
}

function renderHome(){
  renderStories();
  renderCategories();
  renderTrendingRooms();
  renderRecommended();
  renderOnlineRail();
}

function renderOnlineRail(){
  const rail = document.getElementById('online-users-rail');
  if(!rail) return;
  rail.innerHTML = DATA.users.filter(u=>u.online).map(u=>`
    <div class="online-user-row" data-open-profile="${u.id}">
      <div class="vibra-ring"><img class="avatar" src="${u.avatar}"><span class="online-dot"></span></div>
      <div><div class="n">${u.name}</div><div class="s">Online</div></div>
    </div>`).join('');
}

/* ---------------- DISCOVER TAB ---------------- */
function renderDiscoverFilters(){
  const row = document.getElementById('discover-filter-row');
  row.innerHTML = DATA.categories.map(c => `<button class="chip ${c==='All'?'active':''}" data-discover-cat="${c}">${c}</button>`).join('');
}
function renderDiscoverTab(){
  renderDiscoverFilters();
  applyDiscoverFilter('All', '');
}
function applyDiscoverFilter(cat, search){
  let rooms = getRooms();
  if(cat && cat !== 'All') rooms = rooms.filter(r=> r.category === cat);
  if(search){
    const q = search.toLowerCase();
    rooms = rooms.filter(r=> r.name.toLowerCase().includes(q) || r.desc.toLowerCase().includes(q));
  }
  const popular = [...rooms].sort((a,b)=>b.online-a.online).slice(0,4);
  const fresh = [...rooms].slice().reverse().slice(0,4);
  const active = [...rooms].filter(r=>r.live).slice(0,4);
  document.getElementById('popular-list').innerHTML = popular.length ? popular.map(discoverRowHTML).join('') : emptyStateHTML('📭','No rooms match','Try clearing filters.');
  document.getElementById('new-list').innerHTML = fresh.length ? fresh.map(discoverRowHTML).join('') : emptyStateHTML('🆕','Nothing new','Check back soon.');
  document.getElementById('active-list').innerHTML = active.length ? active.map(discoverRowHTML).join('') : emptyStateHTML('💤','All quiet','No rooms are live right now.');
}

/* ---------------------------- CHAT / VOICE ROOM (chat.js, rooms.js) ------ */
let micOn = true;
let speakerOn = true;

/* =========================================================================
   ROOM / CHAT — seats, requests, ambient life, reply, mentions
   ========================================================================= */
async function openRoom(roomId){
  const isApiRoom = typeof roomId === 'number';
  let room = getRooms().find(r=>r.id===roomId);
  if(isApiRoom){
    // Always fetch fresh detail for real rooms rather than trusting the
    // possibly-stale card data (seat occupancy changes constantly).
    try{
      const detail = await Api.getRoom(roomId);
      room = apiRoomToLocal(detail);
      room._seats = detail.seats; // raw backend seat rows, converted below
    }catch(e){
      showToast('Could not load room', 'error');
      return;
    }
  }
  if(!room) return;
  STATE.activeRoom = room;
  const host = DATA.getUser(room.hostId) || room.hostDisplay || STATE.currentUser;
  STATE.isHost = !!(STATE.currentUser && (
    room.hostId === STATE.currentUser.id ||
    room.hostId === 'me' ||
    (isApiRoom && host && host.username === STATE.currentUser.username)
  ));

  document.getElementById('room-title').textContent = room.name;
  document.getElementById('room-online-count').textContent = `${room.online.toLocaleString()} Online`;
  document.getElementById('host-avatar').src = host.avatar;
  document.getElementById('host-name').textContent = host.name;
  document.getElementById('host-ring').classList.add('speaking');

  if(isApiRoom){
    // Build the seat grid from real backend rows instead of the seeded mock.
    ROOM_SEATS_CACHE[roomId] = room._seats.map(s => s.user ? {
      empty:false,
      isMe: s.user.username === STATE.currentUser.username,
      requesting:false,
      name: s.user.username,
      level: s.user.level,
      avatar: s.user.avatar_url,
      muted: s.is_muted,
      speaking:false,
      giftsReceived:0,
      userId: s.user.id,
    } : { empty:true });
  } else if(!ROOM_SEATS_CACHE[roomId]){
    // seed seats once per room per session so reopening doesn't re-shuffle who's on mic
    ROOM_SEATS_CACHE[roomId] = DATA.participantsFor(roomId, 6);
  }
  STATE.mySeatIndex = ROOM_SEATS_CACHE[roomId].findIndex(s=>s.isMe);
  STATE.seatsLocked = false;
  STATE.handRaised = false;
  STATE.handQueue = [];
  STATE.replyTo = null;
  STATE.lastGiftKey = null;
  STATE.giftCombo = 1;
  hideReplyPreview();
  renderMicGrid();

  const box = document.getElementById('chat-messages');
  if(isApiRoom){
    box.innerHTML = '<div class="empty-state"><p>Loading messages…</p></div>';
    try{
      const messages = await Api.listMessages(roomId);
      box.innerHTML = messages.slice().reverse().map(m => chatMessageHTML({
        who: m.user && m.user.username === STATE.currentUser.username ? 'me' : (m.user ? m.user.username : 'system'),
        text: m.text, time: new Date(m.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}),
        system: m.is_system,
        displayName: m.user ? m.user.username : 'Vibra',
        avatarUrl: m.user ? m.user.avatar_url : '',
      })).join('');
    }catch(e){ box.innerHTML = ''; }
    box.scrollTop = box.scrollHeight;
    connectRoomSocket(roomId);
    connectVoice(roomId);
  }else{
    const seed = DATA.messagesSeed[roomId] || DATA.messagesSeed.default;
    box.innerHTML = seed.map(m=> chatMessageHTML(m)).join('');
    box.scrollTop = box.scrollHeight;
  }

  micOn = true; speakerOn = true;
  updateVoiceControlUI();
  updateHandButtonUI();

  const counter = document.getElementById('chat-char-counter');
  if(counter){ counter.textContent = '0/200'; counter.classList.remove('warn'); }
  const fab = document.getElementById('scroll-bottom-fab');
  if(fab) fab.classList.remove('show');
  const sendBtn = document.getElementById('chat-send');
  if(sendBtn) sendBtn.disabled = true;

  openOverlay('screen-room');
  showToast(`You joined ${room.name}`, 'success');
  if(!isApiRoom) startRoomAmbience();
}

/* ---- real-time room WebSocket (API rooms only) ---- */
function connectRoomSocket(roomId){
  if(STATE.roomSocket) STATE.roomSocket.close();
  STATE.roomSocket = Api.connectRoomSocket(roomId, (event) => {
    if(!STATE.activeRoom || STATE.activeRoom.id !== roomId) return; // stale event after leaving
    if(event.event === 'message_new'){
      const box = document.getElementById('chat-messages');
      const mine = event.user && event.user.username === STATE.currentUser.username;
      box.insertAdjacentHTML('beforeend', chatMessageHTML({
        who: mine ? 'me' : (event.user ? event.user.username : 'system'),
        text: event.text,
        time: new Date(event.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}),
        system: event.is_system,
        displayName: event.user ? event.user.username : 'Vibra',
        avatarUrl: event.user ? event.user.avatar_url : '',
      }));
      box.scrollTop = box.scrollHeight;
    }else if(event.event === 'seat_update'){
      const seats = ROOM_SEATS_CACHE[roomId];
      if(!seats || !seats[event.position]) return;
      if(event.action === 'left'){
        seats[event.position] = { empty:true };
      }
      renderMicGrid();
    }else if(event.event === 'presence_update'){
      // lightweight: just nudge the online counter on the next full reload
    }
  });
}
function disconnectRoomSocket(){
  if(STATE.roomSocket){ STATE.roomSocket.close(); STATE.roomSocket = null; }
}

/* ---- real voice (LiveKit) — API rooms only ----
   Everyone who opens the room connects as a listener right away (can_publish
   is decided server-side by voice.js based on whether they hold a seat).
   Taking a seat later just flips setMicrophoneEnabled(true) on the same
   connection — no need to reconnect. */
async function connectVoice(roomId){
  if(typeof LivekitClient === 'undefined'){
    console.error('LiveKit SDK not loaded — check the <script> tag in index.html');
    return;
  }
  try{
    const { token, url } = await Api.getVoiceToken(roomId);
    const room = new LivekitClient.Room();

    room.on(LivekitClient.RoomEvent.TrackSubscribed, (track, publication, participant) => {
      if(track.kind !== LivekitClient.Track.Kind.Audio) return;
      const el = track.attach();
      el.id = `voice-audio-${participant.identity}`;
      el.autoplay = true;
      el.muted = !speakerOn;
      document.body.appendChild(el);
    });
    room.on(LivekitClient.RoomEvent.TrackUnsubscribed, (track) => {
      track.detach().forEach(el => el.remove());
    });
    room.on(LivekitClient.RoomEvent.Disconnected, () => {
      if(STATE.liveKitRoom === room) STATE.liveKitRoom = null;
    });

    await room.connect(url, token);
    await room.startAudio(); // unlocks autoplay now that the user has already clicked "Join"
    STATE.liveKitRoom = room;

    // If we're already seated when this connects (e.g. host reopening their
    // own room), publish the mic immediately.
    if(STATE.mySeatIndex > -1 && micOn){
      await room.localParticipant.setMicrophoneEnabled(true);
    }
  }catch(e){
    console.error('Voice connection failed', e);
    showToast('Could not connect voice (mic/speaker will be visual only)', 'error');
  }
}
function disconnectVoice(){
  if(STATE.liveKitRoom){
    STATE.liveKitRoom.disconnect();
    STATE.liveKitRoom = null;
  }
  document.querySelectorAll('[id^="voice-audio-"]').forEach(el => el.remove());
}

function currentSeats(){
  return STATE.activeRoom ? (ROOM_SEATS_CACHE[STATE.activeRoom.id] || []) : [];
}

function seatHTML(p, idx){
  if(p.empty){
    return `<div class="mic-seat empty" data-seat-idx="${idx}"><div class="avatar-frame">＋</div><span class="uname">Empty seat</span></div>`;
  }
  const crown = p.giftsReceived && p.giftsReceived === Math.max(...currentSeats().filter(s=>!s.empty).map(s=>s.giftsReceived||0)) && p.giftsReceived>0
    ? `<span class="seat-crown">👑</span>` : '';
  return `<div class="mic-seat ${p.muted?'muted':'speaking'} ${p.requesting?'requesting':''}" data-seat-idx="${idx}">
      ${crown}
      <div class="vibra-ring ${p.speaking?'speaking':''}"><img class="avatar" src="${p.avatar}">${p.level?`<span class="seat-level">Lv ${p.level}</span>`:''}</div>
      <span class="uname">${p.isMe? 'You' : p.name}</span>
      <span class="mic-status">${p.muted?'🔇':'🎙️'}</span>
      ${p.giftsReceived?`<span class="seat-gift-pill">🪙×${p.giftsReceived}</span>`:''}
    </div>`;
}

function renderMicGrid(){
  const seats = currentSeats();
  document.getElementById('mic-grid').innerHTML = seats.map((p,idx)=> seatHTML(p, idx)).join('');
}
// Toggles the 'speaking' class on existing seat elements without rebuilding their markup.
// Falls back to a full render if the grid's DOM doesn't match the current seat count
// (e.g. someone joined/left since the last render).
function updateSeatSpeakingClasses(seats){
  const grid = document.getElementById('mic-grid');
  const nodes = grid.children;
  if(nodes.length !== seats.length){ renderMicGrid(); return; }
  seats.forEach((s, idx)=>{
    const ring = nodes[idx] && nodes[idx].querySelector('.vibra-ring');
    if(ring) ring.classList.toggle('speaking', !!s.speaking);
  });
}

function seatUserForActions(seat){
  // Resolve a display-friendly recipient object (works for both real DATA users and synthetic seat occupants)
  return { id: seat.srcUserId || seat.id, name: seat.name, avatar: seat.avatar };
}

function openSeatProfile(idx){
  const seats = currentSeats();
  const seat = seats[idx];
  if(!seat || seat.empty) return;
  document.getElementById('seat-profile-avatar').src = seat.avatar;
  document.getElementById('seat-profile-name').textContent = seat.isMe ? (STATE.currentUser?STATE.currentUser.name:'You') : seat.name;
  document.getElementById('seat-profile-level').textContent = seat.level ? `Lv ${seat.level}` : 'Lv —';
  document.getElementById('seat-profile-sub').textContent = seat.muted ? '🔇 Muted on mic' : '🎙️ Speaking';

  const actions = [];
  if(seat.isMe){
    actions.push(`<button class="btn btn-glass full" data-seat-action="leave-seat">Step down from mic</button>`);
  } else {
    actions.push(`<button class="btn btn-primary" data-seat-action="gift" data-seat-idx="${idx}">🎁 Send Gift</button>`);
    if(seat.srcUserId){
      actions.push(`<button class="btn btn-glass" data-seat-action="profile" data-seat-idx="${idx}">View Profile</button>`);
      actions.push(`<button class="btn btn-glass" data-seat-action="message" data-seat-idx="${idx}">Message</button>`);
    } else {
      actions.push(`<button class="btn btn-glass" data-seat-action="message" data-seat-idx="${idx}">Message</button>`);
    }
    if(STATE.isHost){
      actions.push(`<button class="btn btn-danger full" data-seat-action="remove" data-seat-idx="${idx}">Remove from mic</button>`);
    }
  }
  document.getElementById('seat-profile-actions').innerHTML = actions.join('');
  openModal('seat-profile-modal');
}

function requestSeat(idx){
  const seats = currentSeats();
  const seat = seats[idx];
  if(!seat || !seat.empty) return;
  if(STATE.mySeatIndex > -1){ showToast("You're already on a mic seat", 'info'); return; }
  if(STATE.seatsLocked){ showToast('The host has locked seats right now', 'error'); return; }

  const isApiRoom = STATE.activeRoom && typeof STATE.activeRoom.id === 'number';
  if(isApiRoom){
    seat.requesting = true;
    renderMicGrid();
    Api.takeSeat(STATE.activeRoom.id, idx).then(async ()=>{
      Object.assign(seat, {
        empty:false, requesting:false, isMe:true, name: STATE.currentUser.name,
        level: STATE.currentUser.level || 1, avatar: STATE.currentUser.avatar,
        muted:false, speaking:false, giftsReceived:0,
      });
      STATE.mySeatIndex = idx;
      micOn = true; updateVoiceControlUI();
      renderMicGrid();
      showToast("You're live! Say hi 👋", 'success');
      if(STATE.liveKitRoom){
        try{ await STATE.liveKitRoom.localParticipant.setMicrophoneEnabled(true); }
        catch(e){ showToast('Mic permission was blocked — check your browser settings', 'error'); }
      }
    }).catch(e=>{
      seat.requesting = false;
      renderMicGrid();
      showToast(e.message || 'Could not take seat', 'error');
    });
    return;
  }

  seat.requesting = true;
  renderMicGrid();
  showToast('Request sent to the host…', 'info');
  const roomIdAtRequest = STATE.activeRoom.id;

  setTimeout(()=>{
    // simulate host approval — bail if the user left/switched rooms meanwhile
    if(!STATE.activeRoom || STATE.activeRoom.id !== roomIdAtRequest) return;
    const stillSeats = currentSeats();
    const target = stillSeats[idx];
    if(!target || !target.empty) return;
    Object.assign(target, {
      empty:false, requesting:false, isMe:true, name:'You', level: STATE.currentUser?.level || 1,
      avatar: STATE.currentUser ? STATE.currentUser.avatar : target.avatar,
      muted:false, speaking:false, giftsReceived:0
    });
    STATE.mySeatIndex = idx;
    micOn = true; updateVoiceControlUI();
    renderMicGrid();
    appendChatMessage({who:'system', text:'You joined the mic 🎙️', system:true});
    showToast("You're live! Say hi 👋", 'success');
  }, 1300);
}

function leaveSeat(idx){
  const seats = currentSeats();
  const seat = seats[idx];
  if(!seat) return;
  const isApiRoom = STATE.activeRoom && typeof STATE.activeRoom.id === 'number';
  if(isApiRoom){
    Api.leaveSeat(STATE.activeRoom.id, idx).catch(e => showToast(e.message || 'Could not leave seat', 'error'));
    if(STATE.liveKitRoom) STATE.liveKitRoom.localParticipant.setMicrophoneEnabled(false).catch(()=>{});
  }
  Object.assign(seat, {empty:true, isMe:false, requesting:false, muted:false, speaking:false, name:'', level:null, giftsReceived:0});
  STATE.mySeatIndex = -1;
  renderMicGrid();
  appendChatMessage({who:'system', text:'You stepped down from the mic', system:true});
  closeModal('seat-profile-modal');
}

function removeFromSeat(idx){
  const seats = currentSeats();
  const seat = seats[idx];
  if(!seat || seat.empty) return;
  const name = seat.isMe ? 'You' : seat.name;
  const wasMe = seat.isMe;
  Object.assign(seat, {empty:true, isMe:false, requesting:false, muted:false, speaking:false, name:'', level:null, giftsReceived:0});
  if(wasMe) STATE.mySeatIndex = -1;
  renderMicGrid();
  appendChatMessage({who:'system', text:`${name} was removed from the mic by the host`, system:true});
  closeModal('seat-profile-modal');
  showToast('Removed from mic', 'info');
}

/* ---- raise hand / host request queue ---- */
function updateHandButtonUI(){
  const btn = document.getElementById('vc-hand');
  const label = document.getElementById('vc-hand-label');
  if(!btn) return;
  let badge = btn.querySelector('.vc-badge');
  if(STATE.isHost){
    label.textContent = 'Requests';
    btn.querySelector('.ic').textContent = '🙋';
    btn.classList.remove('hand-active');
    if(STATE.handQueue.length){
      if(!badge){ badge = document.createElement('span'); badge.className='vc-badge'; btn.appendChild(badge); }
      badge.textContent = STATE.handQueue.length;
    } else if(badge){ badge.remove(); }
  } else {
    label.textContent = STATE.handRaised ? 'Raised' : 'Raise';
    btn.querySelector('.ic').textContent = '✋';
    btn.classList.toggle('hand-active', STATE.handRaised);
    if(badge) badge.remove();
  }
}
function handleHandButton(){
  if(STATE.isHost){
    renderRequestsModal();
    openModal('requests-modal');
    return;
  }
  if(STATE.mySeatIndex > -1){ showToast("You're already on mic", 'info'); return; }
  STATE.handRaised = !STATE.handRaised;
  updateHandButtonUI();
  showToast(STATE.handRaised ? 'Hand raised — the host has been notified' : 'Hand lowered', 'info');
}
function renderRequestsModal(){
  const list = document.getElementById('requests-list');
  if(!STATE.handQueue.length){
    list.innerHTML = emptyStateHTML('🙌','No requests yet','Listeners who raise their hand will show up here.');
    return;
  }
  list.innerHTML = STATE.handQueue.map((r,i)=>`
    <div class="request-row">
      <img class="avatar" src="${r.avatar}">
      <div class="meta">${r.name}<span>wants to join the mic</span></div>
      <div class="r-actions">
        <button class="r-approve" data-approve-req="${i}">✓</button>
        <button class="r-decline" data-decline-req="${i}">✕</button>
      </div>
    </div>`).join('');
}
function approveRequest(i){
  const req = STATE.handQueue[i];
  if(!req) return;
  const seats = currentSeats();
  const emptyIdx = seats.findIndex(s=>s.empty);
  if(emptyIdx === -1){ showToast('No empty seats available', 'error'); return; }
  Object.assign(seats[emptyIdx], {empty:false, requesting:false, name:req.name, avatar:req.avatar, level:req.level, muted:false, speaking:false, giftsReceived:0});
  STATE.handQueue.splice(i,1);
  renderMicGrid();
  renderRequestsModal();
  updateHandButtonUI();
  appendChatMessage({who:'system', text:`${req.name} joined the mic 🎙️`, system:true});
  showToast(`${req.name} approved`, 'success');
}
function declineRequest(i){
  const req = STATE.handQueue[i];
  if(!req) return;
  STATE.handQueue.splice(i,1);
  renderRequestsModal();
  updateHandButtonUI();
  showToast(`Declined ${req.name}`, 'info');
}

/* ---- ambient "room feels alive" simulation ---- */
function stopRoomAmbience(){
  STATE.roomTimers.forEach(id=> clearInterval(id));
  STATE.roomTimers = [];
}
function startRoomAmbience(){
  stopRoomAmbience();
  const roomId = STATE.activeRoom.id;

  // speaking rotation among occupied, unmuted seats
  STATE.roomTimers.push(setInterval(()=>{
    if(!STATE.activeRoom || STATE.activeRoom.id !== roomId) return;
    const seats = currentSeats();
    const candidates = seats.filter(s=>!s.empty && !s.muted);
    seats.forEach(s=> s.speaking = false);
    if(candidates.length){ candidates[Math.floor(Math.random()*candidates.length)].speaking = true; }
    updateSeatSpeakingClasses(seats);
  }, 3200));

  // ambient chat / gifts / join-leave / new raised hands
  STATE.roomTimers.push(setInterval(()=>{
    if(!STATE.activeRoom || STATE.activeRoom.id !== roomId) return;
    const roll = Math.random();
    const seats = currentSeats().filter(s=>!s.empty && !s.isMe);
    const pool = DATA.users;

    if(roll < 0.4 && seats.length){
      const speaker = seats[Math.floor(Math.random()*seats.length)];
      const lines = ['Haha true 😂','Wait what happened?','This room is fire tonight 🔥','Anyone else from Kochi?','Lol facts','Can someone add a song?','This convo is so good','👀👀','Same energy fr'];
      appendChatMessage({who:'me', text:lines[Math.floor(Math.random()*lines.length)], _seatName: speaker.isMe?'You':speaker.name, _seatAvatar: speaker.avatar}, true);
    } else if(roll < 0.55){
      const u = pool[Math.floor(Math.random()*pool.length)];
      appendChatMessage({who:'system', text:`${u.name.split(' ')[0]} joined the room`, system:true});
    } else if(roll < 0.68 && STATE.isHost){
      const u = pool[Math.floor(Math.random()*pool.length)];
      if(!STATE.handQueue.some(r=>r.name===u.name.split(' ')[0])){
        STATE.handQueue.push({name:u.name.split(' ')[0], avatar:u.avatar, level:u.level});
        updateHandButtonUI();
      }
    }
  }, 5500));
}

function chatMessageHTML(m){
  if(m.system){
    return `<div class="msg system"><div class="text">${escapeHTML(m.text)}</div></div>`;
  }
  const isMe = m.who === 'me';
  const displayName = m.displayName || (isMe ? (m._seatName || (STATE.currentUser?STATE.currentUser.name:'You')) : (DATA.getUser(m.who)||STATE.currentUser).name);
  const avatar = m.avatarUrl || (isMe ? (m._seatAvatar || (STATE.currentUser?STATE.currentUser.avatar:'')) : (DATA.getUser(m.who)||STATE.currentUser).avatar);
  const time = m.time || nowTime();
  const giftClass = m.gift ? 'gift' : '';
  const replyBlock = m.replyTo ? `<div class="msg-reply-quote">↩ ${escapeHTML(m.replyTo.name)}: ${escapeHTML(m.replyTo.text.slice(0,60))}</div>` : '';
  return `<div class="msg ${giftClass}" data-msg-name="${escapeAttr(displayName.split(' ')[0])}" data-msg-text="${escapeAttr(m.text)}">
    <img class="avatar" src="${avatar}">
    <div class="msg-body">
      <div class="msg-head"><span class="uname">${displayName.split(' ')[0]}</span><span class="time">${time}</span></div>
      ${replyBlock}
      <div class="text">${escapeHTML(m.text)}</div>
    </div>
  </div>`;
}

function appendChatMessage(m, isAmbient){
  const box = document.getElementById('chat-messages');
  if(!box) return;
  const nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 120;
  box.insertAdjacentHTML('beforeend', chatMessageHTML(m));
  if(nearBottom || !isAmbient){
    box.scrollTop = box.scrollHeight;
  } else {
    const fab = document.getElementById('scroll-bottom-fab');
    if(fab) fab.classList.add('show');
  }
}

function escapeHTML(str){
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
function escapeAttr(str){
  return escapeHTML(str).replace(/"/g, '&quot;');
}
function nowTime(){
  const d = new Date();
  let h = d.getHours(); const m = d.getMinutes().toString().padStart(2,'0');
  const ap = h>=12?'PM':'AM'; h = h%12 || 12;
  return `${h}:${m} ${ap}`;
}

function sendMessage(){
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if(!text){ showToast('Message cannot be empty', 'error'); return; }
  const isApiRoom = STATE.activeRoom && typeof STATE.activeRoom.id === 'number';
  if(isApiRoom){
    input.value = '';
    updateCharCounter();
    cancelReply();
    const sendBtn = document.getElementById('chat-send');
    if(sendBtn) sendBtn.disabled = true;
    // no optimistic local append — the backend broadcasts this message back
    // over the WebSocket to everyone in the room, including us, so it
    // renders once the server confirms it rather than twice.
    Api.sendMessage(STATE.activeRoom.id, text).catch(e => showToast(e.message || 'Message failed to send', 'error'));
    return;
  }
  const msg = {who:'me', text, time: nowTime()};
  if(STATE.replyTo) msg.replyTo = STATE.replyTo;
  appendChatMessage(msg);
  input.value = '';
  updateCharCounter();
  cancelReply();
  const sendBtn = document.getElementById('chat-send');
  if(sendBtn) sendBtn.disabled = true;
}

function updateVoiceControlUI(){
  const micBtn = document.getElementById('vc-mic');
  micBtn.classList.toggle('off', !micOn);
  micBtn.querySelector('.ic').textContent = micOn ? '🎤' : '🔇';
  const spBtn = document.getElementById('vc-speaker');
  spBtn.classList.toggle('off', !speakerOn);
  spBtn.querySelector('.ic').textContent = speakerOn ? '🔊' : '🔈';
}
function toggleMicrophone(){
  micOn = !micOn;
  updateVoiceControlUI();
  if(STATE.mySeatIndex > -1){
    const seat = currentSeats()[STATE.mySeatIndex];
    if(seat){ seat.muted = !micOn; renderMicGrid(); }
  }
  if(STATE.liveKitRoom && STATE.liveKitRoom.localParticipant.isMicrophoneEnabled !== micOn){
    STATE.liveKitRoom.localParticipant.setMicrophoneEnabled(micOn).catch(()=>{
      showToast('Mic permission was blocked — check your browser settings', 'error');
    });
  }
  showToast(micOn ? 'Microphone unmuted' : 'Microphone muted', 'info');
}
function toggleSpeaker(){
  speakerOn = !speakerOn;
  updateVoiceControlUI();
  document.querySelectorAll('[id^="voice-audio-"]').forEach(el => { el.muted = !speakerOn; });
  showToast(speakerOn ? 'Speaker on' : 'Speaker off', 'info');
}
function leaveRoom(){
  disconnectRoomSocket();
  disconnectVoice();
  stopRoomAmbience();
  closeOverlay('screen-room');
  showToast('You left the room', 'info');
}

/* ---- reply-to ---- */
function startReply(name, text){
  STATE.replyTo = {name, text};
  document.getElementById('reply-who').textContent = name;
  document.getElementById('reply-snip').textContent = text;
  document.getElementById('reply-preview').classList.add('show');
  document.getElementById('chat-input').focus();
  if(document.getElementById('mention-suggestions').classList.contains('show')) positionMentionSuggestions();
}
function cancelReply(){ STATE.replyTo = null; hideReplyPreview(); }
function hideReplyPreview(){
  const el = document.getElementById('reply-preview');
  if(el) el.classList.remove('show');
  if(document.getElementById('mention-suggestions').classList.contains('show')) positionMentionSuggestions();
}

/* ---- @mentions ---- */
function mentionCandidates(){
  return currentSeats().filter(s=>!s.empty).map(s=> ({name: s.isMe?'You':s.name, avatar:s.avatar}));
}
function positionMentionSuggestions(){
  // The dropdown always sits just above whichever element currently forms the
  // top edge of the input controls (the reply preview when it's showing, or
  // the chat input bar otherwise), so it never overlaps the reply preview.
  const box = document.getElementById('mention-suggestions');
  const reply = document.getElementById('reply-preview');
  const chatBar = document.querySelector('.chat-input-bar');
  const container = box.offsetParent;
  if(!container || !chatBar) return;
  const anchorEl = (reply && reply.classList.contains('show')) ? reply : chatBar;
  const containerRect = container.getBoundingClientRect();
  const anchorRect = anchorEl.getBoundingClientRect();
  const gap = 8;
  box.style.bottom = Math.round(containerRect.bottom - anchorRect.top + gap) + 'px';
}
function updateMentionSuggestions(){
  const input = document.getElementById('chat-input');
  const box = document.getElementById('mention-suggestions');
  const val = input.value;
  const at = val.lastIndexOf('@');
  if(at === -1 || /\s/.test(val.slice(at+1))){ box.classList.remove('show'); return; }
  const partial = val.slice(at+1).toLowerCase();
  const matches = mentionCandidates().filter(c=> c.name.toLowerCase().includes(partial));
  if(!matches.length){ box.classList.remove('show'); return; }
  box.innerHTML = matches.slice(0,5).map(c=>`<div class="mention-row" data-mention="${escapeAttr(c.name)}"><img class="avatar" src="${c.avatar}">@${escapeHTML(c.name)}</div>`).join('');
  box.classList.add('show');
  positionMentionSuggestions();
}
function applyMention(name){
  const input = document.getElementById('chat-input');
  const val = input.value;
  const at = val.lastIndexOf('@');
  input.value = val.slice(0, at) + '@' + name + ' ';
  document.getElementById('mention-suggestions').classList.remove('show');
  input.focus();
}

/* ---- character counter ---- */
function updateCharCounter(){
  const input = document.getElementById('chat-input');
  const counter = document.getElementById('chat-char-counter');
  if(!input || !counter) return;
  const len = input.value.length;
  counter.textContent = `${len}/200`;
  counter.classList.toggle('warn', len >= 180);
}

const EMOJI_SET = ['😀','😂','😍','🥳','🔥','👏','❤️','😢','😮','🙌','💯','🎉','😎','🤔','👋','✨','😴','🤣'];
function renderEmojiPicker(pickerId, inputId){
  const picker = document.getElementById(pickerId);
  picker.innerHTML = EMOJI_SET.map(e=>`<button type="button" data-emoji="${e}">${e}</button>`).join('');
  picker.querySelectorAll('button').forEach(b=>{
    b.addEventListener('click', ()=>{
      const input = document.getElementById(inputId);
      input.value += b.dataset.emoji;
      input.focus();
      if(inputId==='chat-input') updateCharCounter();
    });
  });
}

/* ---- room-more sheet ---- */
function renderRoomMoreSheet(){
  const list = document.getElementById('room-more-list');
  const rows = [];
  rows.push(`<div class="sheet-action-row" data-more-action="share"><div class="ic">🔗</div>Share room</div>`);
  if(STATE.isHost){
    rows.push(`<div class="sheet-action-row" data-more-action="mute-all"><div class="ic">🔇</div>Mute everyone on mic</div>`);
    rows.push(`<div class="sheet-action-row" data-more-action="lock-seats"><div class="ic">${STATE.seatsLocked?'🔓':'🔒'}</div>${STATE.seatsLocked?'Unlock seats':'Lock seats'}</div>`);
    rows.push(`<div class="sheet-action-row" data-more-action="settings"><div class="ic">⚙️</div>Room settings</div>`);
  } else {
    rows.push(`<div class="sheet-action-row" data-more-action="report"><div class="ic">🚩</div>Report room</div>`);
    rows.push(`<div class="sheet-action-row danger" data-more-action="block"><div class="ic">🚫</div>Block host</div>`);
  }
  rows.push(`<div class="sheet-action-row danger" data-more-action="leave"><div class="ic">✕</div>Leave room</div>`);
  list.innerHTML = rows.join('');
}
function handleRoomMoreAction(action){
  closeModal('room-more-modal');
  if(action==='share'){ showToast('Room link copied to clipboard', 'success'); }
  else if(action==='mute-all'){
    currentSeats().forEach(s=>{ if(!s.empty && !s.isMe) s.muted = true; });
    renderMicGrid();
    appendChatMessage({who:'system', text:'The host muted everyone on mic', system:true});
    showToast('Everyone muted', 'info');
  }
  else if(action==='lock-seats'){
    STATE.seatsLocked = !STATE.seatsLocked;
    showToast(STATE.seatsLocked ? 'Seats locked' : 'Seats unlocked', 'info');
  }
  else if(action==='settings'){ showToast('Room settings (demo)', 'info'); }
  else if(action==='report'){ showToast('Report submitted — thanks for keeping Vibra safe', 'success'); }
  else if(action==='block'){ showToast('Host blocked', 'success'); leaveRoom(); }
  else if(action==='leave'){ leaveRoom(); }
}

/* ---------------------------- GIFTS (chat.js) ----------------------------- */
function renderGiftGrid(){
  document.getElementById('gift-grid').innerHTML = DATA.giftCatalog.map(g=>`
    <div class="gift-item" data-gift-id="${g.id}">
      <span class="emoji">${g.emoji}</span>
      <span class="gname">${g.name}</span>
      <span class="gcost">🪙 ${g.cost}</span>
    </div>`).join('');
}
function openGiftModal(recipient, seatIdx){
  STATE.giftRecipient = recipient;
  STATE.giftSeatIdx = (typeof seatIdx === 'number') ? seatIdx : null;
  STATE.selectedGift = null;
  document.getElementById('gift-recipient-avatar').src = recipient.avatar;
  document.getElementById('gift-recipient-name').textContent = recipient.name.split(' ')[0];
  document.getElementById('gift-modal-balance').textContent = getWallet().toLocaleString();
  document.querySelectorAll('.gift-item').forEach(el=>el.classList.remove('selected'));
  updateGiftAffordability();
  openModal('gift-modal');
}
function updateGiftAffordability(){
  const balance = getWallet();
  document.querySelectorAll('.gift-item').forEach(el=>{
    const gift = DATA.giftCatalog.find(g=>g.id===el.dataset.giftId);
    if(gift) el.classList.toggle('unaffordable', gift.cost > balance);
  });
}
function sendGift(){
  if(!STATE.selectedGift){ showToast('Choose a gift first', 'error'); return; }
  const gift = DATA.giftCatalog.find(g=>g.id===STATE.selectedGift);
  const balance = getWallet();
  if(balance < gift.cost){ showToast("You don't have enough coins", 'error'); return; }
  setWallet(balance - gift.cost);

  const tx = Storage.get(Storage.KEYS.TX, []);
  tx.unshift({id:'t'+Date.now(), type:'sent', label:`Sent ${gift.name} to ${STATE.giftRecipient.name.split(' ')[0]}`, time:'Just now', amount:-gift.cost, positive:false});
  Storage.set(Storage.KEYS.TX, tx);

  const history = Storage.get(Storage.KEYS.GIFT_HISTORY, []);
  history.unshift({giftId:gift.id, to:STATE.giftRecipient.id, time:Date.now()});
  Storage.set(Storage.KEYS.GIFT_HISTORY, history);

  // combo tracking: same recipient + same gift within 4s = combo
  const key = STATE.giftRecipient.id + ':' + gift.id;
  const now = Date.now();
  STATE.giftCombo = (STATE.lastGiftKey === key && now - STATE.lastGiftTime < 4000) ? STATE.giftCombo + 1 : 1;
  STATE.lastGiftKey = key;
  STATE.lastGiftTime = now;

  // bump the seat's received-gift counter if this targeted a mic seat
  if(typeof STATE.giftSeatIdx === 'number' && STATE.giftSeatIdx !== null){
    const seat = currentSeats()[STATE.giftSeatIdx];
    if(seat){ seat.giftsReceived = (seat.giftsReceived||0) + gift.cost; }
  }

  closeModal('gift-modal');
  playGiftAnimation(gift.emoji, gift.cost, STATE.giftCombo);
  if(typeof STATE.giftSeatIdx === 'number' && STATE.giftSeatIdx !== null) renderMicGrid();

  if(document.getElementById('screen-room').classList.contains('active')){
    const comboText = STATE.giftCombo > 1 ? ` x${STATE.giftCombo}` : '';
    appendChatMessage({who:'me', gift:true, text:`🎉 You sent a ${gift.name} to ${STATE.giftRecipient.name.split(' ')[0]}${comboText}`});
  }
  showToast(`Gift sent successfully`, 'success');
  updateWalletUI();
}
function playGiftAnimation(emoji, cost, combo){
  const layer = document.getElementById('gift-anim-layer');
  const big = cost >= 500;
  const el = document.createElement('div');
  el.className = 'gift-fly' + (big ? ' big' : '');
  el.textContent = emoji;
  layer.appendChild(el);
  setTimeout(()=> el.remove(), 1100);

  if(big){
    const flash = document.createElement('div');
    flash.className = 'gift-flash';
    layer.appendChild(flash);
    setTimeout(()=> flash.remove(), 1000);
  }
  if(combo > 1){
    const comboEl = document.createElement('div');
    comboEl.className = 'gift-combo';
    comboEl.textContent = `x${combo}`;
    layer.appendChild(comboEl);
    setTimeout(()=> comboEl.remove(), 900);
  }
}

/* ---------------------------- WALLET (wallet.js) --------------------------- */
function updateWalletUI(){
  const bal = getWallet();
  const el = document.getElementById('wallet-balance');
  if(el) el.textContent = bal.toLocaleString();
}
function renderPackages(){
  document.getElementById('package-grid').innerHTML = DATA.packages.map(p=>`
    <div class="package-card glass ${p.best?'best':''}" data-package-id="${p.id}">
      <div class="coins">🪙 ${p.coins.toLocaleString()}</div>
      <div class="price">₹${p.price}</div>
      <button class="btn btn-glass btn-sm btn-block" data-buy-package="${p.id}">Buy</button>
    </div>`).join('');
}
function renderTxHistory(){
  const tx = Storage.get(Storage.KEYS.TX, []);
  document.getElementById('tx-list').innerHTML = tx.map(t=>{
    const icon = t.type==='received'?'🎁':t.type==='purchase'?'💳':'📤';
    return `<div class="tx-row">
      <div class="tx-info"><span class="tx-icon glass">${icon}</span>
        <div class="tx-meta"><div class="t">${t.label}</div><div class="d">${t.time}</div></div>
      </div>
      <div class="amt ${t.positive?'pos':'neg'}">${t.positive?'+':''}${t.amount}</div>
    </div>`;
  }).join('') || emptyStateHTML('🧾','No transactions yet','Your coin activity will show up here.');
}
function openWallet(){
  updateWalletUI();
  renderPackages();
  document.getElementById('tx-history-section').classList.add('hidden');
  openOverlay('screen-wallet');
}
function buyPackage(packageId){
  const pack = DATA.packages.find(p=>p.id===packageId);
  document.getElementById('payment-title').textContent = 'Confirm purchase';
  document.getElementById('payment-desc').textContent = `Buy ${pack.coins.toLocaleString()} Coins for ₹${pack.price}?`;
  document.getElementById('confirm-payment').dataset.packageId = packageId;
  openModal('payment-modal');
}
function confirmPurchase(){
  const packageId = document.getElementById('confirm-payment').dataset.packageId;
  const pack = DATA.packages.find(p=>p.id===packageId);
  if(!pack) return;
  setWallet(getWallet() + pack.coins);
  const tx = Storage.get(Storage.KEYS.TX, []);
  tx.unshift({id:'t'+Date.now(), type:'purchase', label:`Purchased ${pack.coins.toLocaleString()} Coins`, time:'Just now', amount:pack.coins, positive:true});
  Storage.set(Storage.KEYS.TX, tx);
  closeModal('payment-modal');
  updateWalletUI();
  showToast('Coins added to your wallet', 'success');
}

/* ---------------------------- PROFILE (profile.js) ------------------------- */
function isFollowing(userId){
  return Storage.get(Storage.KEYS.FOLLOWING, []).includes(userId);
}
function toggleFollow(userId){
  let list = Storage.get(Storage.KEYS.FOLLOWING, []);
  if(list.includes(userId)){
    list = list.filter(id=>id!==userId);
  } else {
    list.push(userId);
    showToast('You are now following this user', 'success');
  }
  Storage.set(Storage.KEYS.FOLLOWING, list);
}

function profileHTML(user, isSelf){
  const following = isFollowing(user.id);
  const badges = ['🏆 Top Host','🎤 Verified Voice','🔥 30-Day Streak'];
  return `
    <div class="profile-cover" style="background:${DATA.gradients[user.level % DATA.gradients.length]};"></div>
    <div class="profile-main">
      <img class="avatar" src="${user.avatar}">
      <div class="profile-name-row"><h2>${user.name}</h2><span class="level-badge">Lvl ${user.level}</span></div>
      <div class="profile-username">@${user.username}</div>
      <div class="profile-bio">${user.bio}</div>
      <div class="profile-country">📍 ${user.country}</div>
      <div class="profile-stats">
        <div class="stat"><b>${user.followers.toLocaleString()}</b><span>Followers</span></div>
        <div class="stat"><b>${user.following.toLocaleString()}</b><span>Following</span></div>
        <div class="stat"><b>${user.level}</b><span>Level</span></div>
      </div>
      <div class="profile-btn-row">
        ${isSelf ? `<button class="btn btn-glass" style="flex:1;" data-open-settings>Edit Profile</button>`
        : `<button class="btn ${following?'btn-glass':'btn-primary'}" style="flex:1;" data-follow="${user.id}">${following?'Following':'Follow'}</button>
           <button class="btn btn-glass" style="flex:1;" data-dm-user="${user.id}">Message</button>
           <button class="btn btn-glass" data-gift-user="${user.id}" style="flex:0.6;">🎁</button>`}
      </div>
    </div>
    <div class="badge-row">${badges.map(b=>`<div class="badge-pill">${b}</div>`).join('')}</div>
    <div class="tab-row">
      <div class="tab-item active" data-tab="posts">Posts</div>
      <div class="tab-item" data-tab="gifts">Gifts</div>
      <div class="tab-item" data-tab="achievements">Achievements</div>
    </div>
    <div class="tab-panel active" data-panel="posts">
      <div class="posts-grid">${Array.from({length:9}).map((_,i)=>`<div class="post-tile" style="background:${DATA.gradients[i%DATA.gradients.length]}; opacity:.8;"></div>`).join('')}</div>
    </div>
    <div class="tab-panel" data-panel="gifts">
      <div class="gifts-received-grid">
        ${DATA.giftCatalog.map(g=>`<div class="g"><div class="emoji">${g.emoji}</div><div class="cnt">×${Math.floor(seededRandom(user.id+g.id)*40)}</div></div>`).join('')}
      </div>
    </div>
    <div class="tab-panel" data-panel="achievements">
      ${[['🏅','First Room Joined','Joined your first Vibra room'],['🎙️','Voice Star','Spoke in 10+ voice rooms'],['💎','Big Spender','Sent over 1,000 coins in gifts'],['🌟','Rising Star','Reached level 10']].map(a=>`
      <div class="achieve-row"><div class="ic">${a[0]}</div><div><div class="t">${a[1]}</div><div class="d">${a[2]}</div></div></div>`).join('')}
    </div>
  `;
}

function renderOwnProfile(){
  const u = STATE.currentUser;
  const selfAsProfileUser = {
    ...u,
    bio: u.bio || 'New to Vibra ✨ Say hi!',
    country: u.country || 'India 🇮🇳',
    followers: u.followers ?? 128,
    following: u.following ?? 76,
    level: u.level ?? 4,
  };
  document.getElementById('profile-render-target').innerHTML = profileHTML(selfAsProfileUser, true);
  bindProfileTabs(document.getElementById('profile-render-target'));
}
function openUserProfile(userId){
  const user = DATA.getUser(userId);
  if(!user) return;
  const target = document.getElementById('user-profile-target');
  target.innerHTML = profileHTML(user, false);
  bindProfileTabs(target);
  openOverlay('screen-user-profile');
}
function bindProfileTabs(container){
  container.querySelectorAll('.tab-item').forEach(tab=>{
    tab.addEventListener('click', ()=>{
      container.querySelectorAll('.tab-item').forEach(t=>t.classList.remove('active'));
      container.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
      tab.classList.add('active');
      container.querySelector(`.tab-panel[data-panel="${tab.dataset.tab}"]`).classList.add('active');
    });
  });
}

/* ---------------------------- MESSAGES / DM (profile.js, chat.js) --------- */
const dmThreads = {}; // userId -> array of {who:'me'|'them', text, time}
function seedDMThread(userId){
  if(dmThreads[userId]) return;
  const seedEntry = DATA.dmSeed.find(d=>d.userId===userId);
  dmThreads[userId] = [
    {who:'them', text: seedEntry ? seedEntry.last : "Hey there!", time: nowTime()}
  ];
}

function renderMessagesList(){
  const list = document.getElementById('messages-list');
  list.innerHTML = DATA.dmSeed.map(d=>{
    const u = DATA.getUser(d.userId);
    return `<div class="msg-list-row ${d.unread?'unread':''}" data-open-dm="${d.userId}">
      <div class="vibra-ring"><img class="avatar" src="${u.avatar}">${u.online?'<span class="online-dot"></span>':''}</div>
      <div class="meta">
        <div class="top"><span class="name">${u.name}</span><span class="time">${d.time}</span></div>
        <div class="preview">${d.last}</div>
      </div>
      ${d.unread ? '<span class="unread-dot"></span>' : ''}
    </div>`;
  }).join('');
}

function openDM(userId){
  const u = DATA.getUser(userId);
  if(!u) return;
  STATE.activeDM = userId;
  seedDMThread(userId);
  document.getElementById('dm-avatar').src = u.avatar;
  document.getElementById('dm-name').textContent = u.name;
  document.getElementById('dm-status').textContent = u.online ? 'Online' : 'Offline';
  document.getElementById('dm-input').value = '';
  const dmSendBtn = document.getElementById('dm-send');
  if(dmSendBtn) dmSendBtn.disabled = true;
  renderDMBody();
  openOverlay('screen-dm');
}
function renderDMBody(){
  const body = document.getElementById('dm-body');
  const thread = dmThreads[STATE.activeDM] || [];
  body.innerHTML = thread.map(m=>`
    <div class="dm-msg ${m.who==='me'?'me':'them'}">${escapeHTML(m.text)}<div class="dm-time">${m.time}</div></div>
  `).join('');
  body.scrollTop = body.scrollHeight;
}
function sendDM(){
  const input = document.getElementById('dm-input');
  const text = input.value.trim();
  if(!STATE.activeDM) return;
  if(!text){ showToast('Message cannot be empty', 'error'); return; }
  dmThreads[STATE.activeDM].push({who:'me', text, time: nowTime()});
  input.value = '';
  const dmSendBtn = document.getElementById('dm-send');
  if(dmSendBtn) dmSendBtn.disabled = true;
  renderDMBody();
  showToast('Message sent successfully', 'success');
}

/* ---------------------------- NOTIFICATIONS -------------------------------- */
function notifIconMeta(type){
  switch(type){
    case 'follow': return {ic:'👤', bg:'rgba(183,33,255,0.15)'};
    case 'gift': return {ic:'🎁', bg:'rgba(255,200,87,0.15)'};
    case 'invite': return {ic:'📣', bg:'rgba(47,230,216,0.15)'};
    case 'message': return {ic:'💬', bg:'rgba(255,62,165,0.15)'};
    default: return {ic:'🔔', bg:'rgba(255,255,255,0.08)'};
  }
}
function renderNotifications(){
  const list = document.getElementById('notifications-list');
  list.innerHTML = DATA.notifSeed.map(n=>{
    const meta = notifIconMeta(n.type);
    const u = n.userId ? DATA.getUser(n.userId) : null;
    return `<div class="notif-row ${n.unread?'unread':''}">
      <div class="ic" style="background:${meta.bg};">${meta.ic}</div>
      <div><div class="t">${u ? `<b>${u.name}</b> ${n.text}` : n.text}</div><div class="time">${n.time}</div></div>
    </div>`;
  }).join('');
  document.getElementById('notif-badge').textContent = DATA.notifSeed.filter(n=>n.unread).length;
}

/* ---------------------------- CREATE ROOM (rooms.js) ------------------------ */
let selectedPrivacy = 'public';
function renderCreateRoomCategories(){
  const wrap = document.getElementById('cr-category');
  wrap.innerHTML = DATA.categories.filter(c=>c!=='All' && c!=='Trending').map((c,i)=>
    `<button type="button" class="chip ${i===0?'active':''}" data-cr-cat="${c}">${c}</button>`).join('');
}
async function createRoom(name, desc, category){
  try{
    const room = await Api.createRoom({ name, category: category.toLowerCase(), description: desc || 'A new Vibra room.' });
    await refreshApiRooms();
    renderHome();
    showToast('Room created successfully', 'success');
    openRoom(room.id);
  }catch(e){
    showToast(e.message || 'Could not create room', 'error');
  }
}

/* ---------------------------- SETTINGS (settings.js) ------------------------ */
function doLogout(){
  Storage.set(Storage.KEYS.USER, null);
  STATE.currentUser = null;
  closeModal('logout-modal');
  closeOverlay('screen-settings');
  document.getElementById('app-shell').classList.remove('active');
  document.getElementById('screen-login').classList.remove('hidden');
  document.getElementById('login-form').reset();
  showToast('You have been logged out', 'info');
}

/* ============================================================================
   EVENT BINDING / INIT  (app.js)
   ============================================================================ */
function bindPasswordToggles(){
  document.querySelectorAll('.pw-toggle').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const input = document.getElementById(btn.dataset.target);
      input.type = input.type === 'password' ? 'text' : 'password';
      btn.textContent = input.type === 'password' ? '👁️' : '🙈';
    });
  });
}

function bindAuth(){
  document.getElementById('go-signup').addEventListener('click', ()=> switchAuthScreen('screen-signup','screen-login'));
  document.getElementById('go-login').addEventListener('click', ()=> switchAuthScreen('screen-login','screen-signup'));

  document.getElementById('login-form').addEventListener('submit', e=>{
    e.preventDefault();
    if(!validateLogin()) return;
    const id = document.getElementById('login-id').value.trim();
    const pw = document.getElementById('login-pw').value;
    doLogin(id, pw);
  });

  document.getElementById('guest-btn').addEventListener('click', async ()=>{
    try{
      const profile = await Api.guestLogin();
      loginAs({
        name: profile.username, username: profile.username,
        avatar: profile.avatar_url || DATA.avatarFor(profile.username),
        level: profile.level,
      });
    }catch(e){
      showToast(e.message || 'Guest login failed', 'error');
    }
  });
  document.getElementById('forgot-btn').addEventListener('click', ()=> showToast('Password reset link sent (demo)', 'info'));
  document.getElementById('google-btn').addEventListener('click', ()=> loginAs({ name:'Sahil Menon', username:'sahilm', avatar: DATA.avatarFor('sahilm-google') }));
  document.getElementById('apple-btn').addEventListener('click', ()=> loginAs({ name:'Sahil Menon', username:'sahilm', avatar: DATA.avatarFor('sahilm-apple') }));

  document.getElementById('signup-form').addEventListener('submit', e=>{
    e.preventDefault();
    const name = document.getElementById('su-name').value.trim();
    const username = document.getElementById('su-username').value.trim();
    const email = document.getElementById('su-email').value.trim();
    const dob = document.getElementById('su-dob').value;
    const pw = document.getElementById('su-pw').value;
    const pw2 = document.getElementById('su-pw2').value;

    let ok = true;
    setFieldError('su-name-field', !name); if(!name) ok=false;
    setFieldError('su-username-field', username.length<3); if(username.length<3) ok=false;
    const emailOk = /^\S+@\S+\.\S+$/.test(email);
    setFieldError('su-email-field', !emailOk); if(!emailOk) ok=false;
    setFieldError('su-dob-field', !dob); if(!dob) ok=false;
    setFieldError('su-pw-field', pw.length<8); if(pw.length<8) ok=false;
    setFieldError('su-pw2-field', pw!==pw2 || !pw2); if(pw!==pw2 || !pw2) ok=false;
    if(!ok) return;

    doSignup({ name, username, email, dob, password: pw, avatar: DATA.avatarFor(username) });
  });
}

function bindNav(){
  document.querySelectorAll('[data-nav]').forEach(el=>{
    el.addEventListener('click', ()=> navigateTo(el.dataset.nav));
  });
  document.getElementById('side-wallet')?.addEventListener('click', openWallet);
  document.getElementById('side-settings')?.addEventListener('click', ()=> openOverlay('screen-settings'));
}

function bindHome(){
  document.getElementById('category-row').addEventListener('click', e=>{
    const chip = e.target.closest('[data-cat]');
    if(!chip) return;
    STATE.activeCategory = chip.dataset.cat;
    renderCategories();
    renderTrendingRooms();
    renderRecommended();
  });
  document.getElementById('room-search').addEventListener('input', e=>{
    renderRecommended();
    const rooms = filteredRooms(e.target.value);
    document.getElementById('trending-rooms').innerHTML = rooms.length ? rooms.map(roomCardHTML).join('') : emptyStateHTML('🔍','No rooms found','Try a different search term.');
  });
  document.getElementById('open-notifications').addEventListener('click', ()=>{ renderNotifications(); openOverlay('screen-notifications'); });
  document.getElementById('open-notifications-2').addEventListener('click', ()=>{ renderNotifications(); openOverlay('screen-notifications'); });
  document.getElementById('open-wallet-mini').addEventListener('click', openWallet);
  document.getElementById('open-profile-mini').addEventListener('click', ()=> navigateTo('profile'));
  document.getElementById('open-settings')?.addEventListener('click', ()=> openOverlay('screen-settings'));

  // Delegated: join room / open profile from home & discover & recommended
  document.body.addEventListener('click', e=>{
    const joinBtn = e.target.closest('[data-join-room]');
    if(joinBtn){ openRoom(parseRoomId(joinBtn.dataset.joinRoom)); return; }
    const roomCard = e.target.closest('[data-room-id]');
    if(roomCard && !e.target.closest('[data-join-room]')){ openRoom(parseRoomId(roomCard.dataset.roomId)); return; }
    const storyProfile = e.target.closest('[data-open-profile]');
    if(storyProfile){ openUserProfile(storyProfile.dataset.openProfile); return; }
  });
}

// data-* attributes are always strings; API room ids are numeric, mock room
// ids look like 'r1721...' — convert back to a number only when it's a pure
// digit string, so openRoom's typeof check can tell the two apart.
function parseRoomId(raw){
  return /^\d+$/.test(raw) ? parseInt(raw, 10) : raw;
}

function bindDiscover(){
  document.getElementById('discover-filter-row').addEventListener('click', e=>{
    const chip = e.target.closest('[data-discover-cat]');
    if(!chip) return;
    document.querySelectorAll('#discover-filter-row .chip').forEach(c=>c.classList.remove('active'));
    chip.classList.add('active');
    applyDiscoverFilter(chip.dataset.discoverCat, document.getElementById('discover-search').value);
  });
  document.getElementById('discover-search').addEventListener('input', e=>{
    const activeChip = document.querySelector('#discover-filter-row .chip.active');
    applyDiscoverFilter(activeChip ? activeChip.dataset.discoverCat : 'All', e.target.value);
  });
}

function bindRoomScreen(){
  document.getElementById('room-back').addEventListener('click', leaveRoom);
  document.getElementById('room-share').addEventListener('click', ()=> showToast('Room link copied to clipboard', 'success'));
  document.getElementById('room-more').addEventListener('click', ()=>{
    renderRoomMoreSheet();
    openModal('room-more-modal');
  });
  document.getElementById('room-more-list').addEventListener('click', e=>{
    const row = e.target.closest('[data-more-action]');
    if(row) handleRoomMoreAction(row.dataset.moreAction);
  });

  document.getElementById('chat-send').addEventListener('click', sendMessage);
  document.getElementById('chat-send').disabled = true;
  document.getElementById('chat-input').addEventListener('keydown', e=>{ if(e.key==='Enter') sendMessage(); });
  document.getElementById('chat-input').addEventListener('input', ()=>{
    updateCharCounter();
    updateMentionSuggestions();
    document.getElementById('chat-send').disabled = !document.getElementById('chat-input').value.trim();
  });
  document.getElementById('mention-suggestions').addEventListener('click', e=>{
    const row = e.target.closest('[data-mention]');
    if(row) applyMention(row.dataset.mention);
  });
  document.getElementById('reply-cancel').addEventListener('click', cancelReply);
  document.getElementById('chat-messages').addEventListener('click', e=>{
    const msg = e.target.closest('.msg:not(.system)');
    if(!msg) return;
    startReply(msg.dataset.msgName, msg.dataset.msgText);
  });
  document.getElementById('scroll-bottom-fab').addEventListener('click', ()=>{
    const box = document.getElementById('chat-messages');
    box.scrollTop = box.scrollHeight;
    document.getElementById('scroll-bottom-fab').classList.remove('show');
  });
  document.getElementById('chat-messages').addEventListener('scroll', ()=>{
    const box = document.getElementById('chat-messages');
    if(box.scrollHeight - box.scrollTop - box.clientHeight < 40){
      document.getElementById('scroll-bottom-fab').classList.remove('show');
    }
  });

  // tappable mic seats
  document.getElementById('mic-grid').addEventListener('click', e=>{
    const seatEl = e.target.closest('[data-seat-idx]');
    if(!seatEl) return;
    const idx = parseInt(seatEl.dataset.seatIdx, 10);
    const seat = currentSeats()[idx];
    if(seat && seat.empty) requestSeat(idx);
    else if(seat) openSeatProfile(idx);
  });
  document.querySelector('.host-block').addEventListener('click', ()=>{
    if(!STATE.activeRoom) return;
    const host = DATA.getUser(STATE.activeRoom.hostId) || STATE.activeRoom.hostDisplay || STATE.currentUser;
    if(!STATE.isHost) openGiftModal(host);
  });
  document.getElementById('seat-profile-actions').addEventListener('click', e=>{
    const btn = e.target.closest('[data-seat-action]');
    if(!btn) return;
    const action = btn.dataset.seatAction;
    const idx = btn.dataset.seatIdx !== undefined ? parseInt(btn.dataset.seatIdx,10) : null;
    if(action === 'leave-seat'){ leaveSeat(STATE.mySeatIndex); }
    else if(action === 'gift'){ const seat = currentSeats()[idx]; closeModal('seat-profile-modal'); openGiftModal(seatUserForActions(seat), idx); }
    else if(action === 'profile'){ const seat = currentSeats()[idx]; closeModal('seat-profile-modal'); if(seat.srcUserId) openUserProfile(seat.srcUserId); }
    else if(action === 'message'){ const seat = currentSeats()[idx]; closeModal('seat-profile-modal'); if(seat.srcUserId) openDM(seat.srcUserId); else showToast('Messaging (demo)', 'info'); }
    else if(action === 'remove'){ removeFromSeat(idx); }
  });

  document.getElementById('emoji-toggle').addEventListener('click', ()=>{
    document.getElementById('emoji-picker').classList.toggle('show');
  });
  renderEmojiPicker('emoji-picker','chat-input');

  document.getElementById('gift-open-btn').addEventListener('click', ()=>{
    const host = DATA.getUser(STATE.activeRoom.hostId) || STATE.activeRoom.hostDisplay || STATE.currentUser;
    openGiftModal(host);
  });
  document.getElementById('vc-gift').addEventListener('click', ()=>{
    const host = DATA.getUser(STATE.activeRoom.hostId) || STATE.activeRoom.hostDisplay || STATE.currentUser;
    openGiftModal(host);
  });
  document.getElementById('vc-mic').addEventListener('click', toggleMicrophone);
  document.getElementById('vc-speaker').addEventListener('click', toggleSpeaker);
  document.getElementById('vc-hand').addEventListener('click', handleHandButton);
  document.getElementById('vc-leave').addEventListener('click', leaveRoom);
  document.getElementById('vc-participants').addEventListener('click', ()=>{
    const seats = currentSeats().filter(p=>!p.empty);
    document.getElementById('participants-list').innerHTML = seats.length ? seats.map((p,realIdx)=>{
      const idx = currentSeats().indexOf(p);
      return `<div class="discover-row">
        <img class="thumb avatar" style="border-radius:50%;" src="${p.avatar}">
        <div class="meta"><div class="name">${p.isMe?'You':p.name}</div><div class="sub">${p.muted?'Muted':'Speaking'}${p.giftsReceived?` · 🪙${p.giftsReceived} received`:''}</div></div>
        ${!p.isMe?`<button class="join-mini btn-glass" data-participant-gift="${idx}">🎁</button>`:''}
      </div>`;
    }).join('') : emptyStateHTML('👥','Nobody on mic yet','Tap an empty seat to hop on!');
    openModal('participants-modal');
  });
  document.getElementById('participants-list').addEventListener('click', e=>{
    const btn = e.target.closest('[data-participant-gift]');
    if(!btn) return;
    const idx = parseInt(btn.dataset.participantGift, 10);
    const seat = currentSeats()[idx];
    if(seat){ closeModal('participants-modal'); openGiftModal(seatUserForActions(seat), idx); }
  });

  document.getElementById('requests-list').addEventListener('click', e=>{
    const approveBtn = e.target.closest('[data-approve-req]');
    if(approveBtn){ approveRequest(parseInt(approveBtn.dataset.approveReq,10)); return; }
    const declineBtn = e.target.closest('[data-decline-req]');
    if(declineBtn){ declineRequest(parseInt(declineBtn.dataset.declineReq,10)); return; }
  });
}

function bindGifts(){
  document.getElementById('gift-grid').addEventListener('click', e=>{
    const item = e.target.closest('[data-gift-id]');
    if(!item) return;
    if(item.classList.contains('unaffordable')){
      showToast("You don't have enough coins for this gift", 'error');
      return;
    }
    document.querySelectorAll('.gift-item').forEach(el=>el.classList.remove('selected'));
    item.classList.add('selected');
    STATE.selectedGift = item.dataset.giftId;
  });
  document.getElementById('gift-send-btn').addEventListener('click', sendGift);
  document.body.addEventListener('click', e=>{
    const giftUserBtn = e.target.closest('[data-gift-user]');
    if(giftUserBtn){ openGiftModal(DATA.getUser(giftUserBtn.dataset.giftUser)); return; }
  });
  renderGiftGrid();
}

function bindWallet(){
  document.getElementById('buy-coins-btn').addEventListener('click', ()=>{
    document.getElementById('tx-history-section').classList.add('hidden');
    document.querySelector('#screen-wallet .package-grid').closest('.ov-body').scrollTop = 0;
  });
  document.getElementById('tx-history-btn').addEventListener('click', ()=>{
    document.getElementById('tx-history-section').classList.toggle('hidden');
    renderTxHistory();
  });
  document.getElementById('package-grid').addEventListener('click', e=>{
    const btn = e.target.closest('[data-buy-package]');
    if(!btn) return;
    buyPackage(btn.dataset.buyPackage);
  });
  document.getElementById('confirm-payment').addEventListener('click', confirmPurchase);
}

function bindProfileAndMessages(){
  document.body.addEventListener('click', e=>{
    const followBtn = e.target.closest('[data-follow]');
    if(followBtn){
      toggleFollow(followBtn.dataset.follow);
      const user = DATA.getUser(followBtn.dataset.follow);
      openUserProfile(user.id);
      return;
    }
    const dmBtn = e.target.closest('[data-dm-user]');
    if(dmBtn){ openDM(dmBtn.dataset.dmUser); return; }
    const openDmRow = e.target.closest('[data-open-dm]');
    if(openDmRow){ openDM(openDmRow.dataset.openDm); return; }
    const settingsOpen = e.target.closest('[data-open-settings]');
    if(settingsOpen){ openOverlay('screen-settings'); return; }
  });

  document.getElementById('dm-send').addEventListener('click', sendDM);
  document.getElementById('dm-send').disabled = true;
  document.getElementById('dm-input').addEventListener('keydown', e=>{ if(e.key==='Enter') sendDM(); });
  document.getElementById('dm-input').addEventListener('input', e=>{
    document.getElementById('dm-send').disabled = !e.target.value.trim();
  });
  document.getElementById('dm-emoji-toggle').addEventListener('click', ()=> document.getElementById('dm-emoji-picker').classList.toggle('show'));
  renderEmojiPicker('dm-emoji-picker','dm-input');

  document.getElementById('messages-search').addEventListener('input', e=>{
    const q = e.target.value.toLowerCase();
    let visibleCount = 0;
    document.querySelectorAll('#messages-list .msg-list-row').forEach(row=>{
      const text = row.textContent.toLowerCase();
      const matches = text.includes(q);
      row.style.display = matches ? '' : 'none';
      if(matches) visibleCount++;
    });
    const emptyEl = document.getElementById('messages-empty');
    if(q && visibleCount === 0){
      emptyEl.innerHTML = emptyStateHTML('🔍','No messages match','Try a different name or keyword.');
      emptyEl.classList.remove('hidden');
    } else {
      emptyEl.classList.add('hidden');
    }
  });
}

function bindCreateRoom(){
  renderCreateRoomCategories();
  document.getElementById('cr-category').addEventListener('click', e=>{
    const chip = e.target.closest('[data-cr-cat]');
    if(!chip) return;
    document.querySelectorAll('#cr-category .chip').forEach(c=>c.classList.remove('active'));
    chip.classList.add('active');
  });
  document.querySelectorAll('.privacy-opt').forEach(opt=>{
    opt.addEventListener('click', ()=>{
      document.querySelectorAll('.privacy-opt').forEach(o=>o.classList.remove('active'));
      opt.classList.add('active');
      selectedPrivacy = opt.dataset.privacy;
    });
  });
  document.getElementById('cr-image-picker').addEventListener('click', ()=> showToast('Image upload (demo)', 'info'));
  document.getElementById('create-room-form').addEventListener('submit', e=>{
    e.preventDefault();
    const name = document.getElementById('cr-name').value.trim();
    if(!name){ showToast('Room name is required', 'error'); return; }
    const desc = document.getElementById('cr-desc').value.trim();
    const activeCatChip = document.querySelector('#cr-category .chip.active');
    const category = activeCatChip ? activeCatChip.dataset.crCat : 'Talk';
    createRoom(name, desc, category);
    closeOverlay('screen-create-room');
    e.target.reset();
    document.querySelectorAll('#cr-category .chip').forEach((c,i)=>c.classList.toggle('active', i===0));
  });
}

function bindSettings(){
  document.getElementById('logout-btn').addEventListener('click', ()=> openModal('logout-modal'));
  document.getElementById('confirm-logout').addEventListener('click', doLogout);
  document.getElementById('toggle-notif').addEventListener('click', function(){ this.classList.toggle('on'); });
  document.getElementById('toggle-dark').addEventListener('click', function(){ this.classList.toggle('on'); showToast('Dark mode is the only mode on Vibra 😉','info'); this.classList.add('on'); });
}

function bindOverlaysAndModals(){
  document.querySelectorAll('[data-close-overlay]').forEach(btn=>{
    btn.addEventListener('click', ()=> closeOverlay(btn.dataset.closeOverlay));
  });
  document.querySelectorAll('[data-close-modal]').forEach(btn=>{
    btn.addEventListener('click', ()=> closeModal(btn.dataset.closeModal));
  });
  document.querySelectorAll('.modal-backdrop').forEach(bg=>{
    bg.addEventListener('click', e=>{ if(e.target === bg) bg.classList.remove('show'); });
  });
}

function initSplash(){
  setTimeout(()=>{
    document.getElementById('screen-splash').style.transition = 'opacity .4s ease';
    document.getElementById('screen-splash').style.opacity = '0';
    setTimeout(()=>{
      document.getElementById('screen-splash').classList.add('hidden');
      const existing = Storage.get(Storage.KEYS.USER);
      if(existing){
        STATE.currentUser = existing;
        enterApp();
      } else {
        document.getElementById('screen-login').classList.remove('hidden');
      }
    }, 400);
  }, 2200);
}

function bindGlobalKeyboard(){
  document.addEventListener('keydown', e=>{
    if(e.key !== 'Escape') return;
    const openModalEl = document.querySelector('.modal-backdrop.show');
    if(openModalEl){ openModalEl.classList.remove('show'); return; }
    const openOverlayEl = document.querySelector('.overlay-screen.active');
    if(openOverlayEl){
      if(openOverlayEl.id === 'screen-room'){ leaveRoom(); }
      else { closeOverlay(openOverlayEl.id); }
    }
  });
}


function init(){
  initStorageDefaults();
  bindPasswordToggles();
  bindAuth();
  bindNav();
  bindHome();
  bindDiscover();
  bindRoomScreen();
  bindGifts();
  bindWallet();
  bindProfileAndMessages();
  bindCreateRoom();
  bindSettings();
  bindOverlaysAndModals();
  bindGlobalKeyboard();
  renderDiscoverTab();
  // Render all Lucide icons declared with data-lucide attributes
  if(window.lucide){ lucide.createIcons(); }
  initSplash();
}

document.addEventListener('DOMContentLoaded', init);

