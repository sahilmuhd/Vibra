/* ============================================================================
   social.js — phase 5: families, CP & best friends, profile visitors,
   friends in rooms, scheduled rooms, voice messages and stickers.
   Uses app.js helpers at call time (ic, escapeHTML, imgSrc, showToast, STATE, Api ...).
   ============================================================================ */
const FAMILY_EMBLEMS = ['crown', 'flame', 'star', 'moon', 'heart', 'zap', 'gem', 'leaf', 'music', 'rocket'];
function emblemIcon(k){ return FAMILY_EMBLEMS.includes(k) ? k : 'crown'; }
function emblemHTML(k, size){ return `<span class="fam-emblem ${size || ''} e-${emblemIcon(k)}">${ic(emblemIcon(k))}</span>`; }
function timeAgo(iso){
  const s = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if(s < 60) return 'just now';
  if(s < 3600) return `${Math.floor(s / 60)}m ago`;
  if(s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
function userRowHTML(u, right, attrs){
  return `<div class="soc-row" ${attrs || ''}>
    <img class="avatar" src="${imgSrc(u.avatar_url)}" alt="">
    <div class="soc-meta"><div class="soc-name">${escapeHTML(u.username)}</div><div class="soc-bdg">${badgesHTML(u)}</div></div>
    ${right || ''}</div>`;
}

/* ---------------------------------------------------------------- families */
let familyState = { id: null, tab: 'members', data: null };
async function openFamilies(){
  openOverlay('screen-family');
  const mine = STATE.currentUser && STATE.currentUser.family;
  if(mine && mine.id) return openFamily(mine.id);
  renderFamilyBrowse();
}
async function renderFamilyBrowse(q){
  familyState = { id: null, tab: 'members', data: null };
  document.getElementById('family-title').textContent = 'Families';
  const body = document.getElementById('family-body');
  if(q === undefined){
    body.innerHTML = `
      <div class="fam-intro">${emblemHTML('crown', 'lg')}<div><b>Join a family</b><span>Badge next to your name, family chat, family rooms and a weekly ranking.</span></div></div>
      <div class="fam-search"><div class="input-wrap"><input type="search" id="family-search" placeholder="Search families or tags" maxlength="40"></div>
        <button type="button" class="btn btn-primary btn-sm" id="family-create-open">${ic('plus')} Create</button></div>
      <div id="family-list">${emptyStateHTML('⏳', 'Loading…', '')}</div>`;
  }
  try{
    const res = await Api.listFamilies(q || '');
    const list = document.getElementById('family-list');
    if(!list) return;
    list.innerHTML = res.families.length ? res.families.map((f, i) => `
      <button type="button" class="fam-card" data-open-family="${Number(f.id)}">
        <span class="fam-rank">${i + 1}</span>${emblemHTML(f.emblem)}
        <span class="fam-info"><b>${escapeHTML(f.name)}</b><span><span class="bdg fam">${escapeHTML(f.tag)}</span> ${Number(f.members)}/${Number(f.max_members)} members</span></span>
        <span class="fam-score">${ic('coins')}${escapeHTML(formatScore(f.score))}</span>
      </button>`).join('')
      : emptyStateHTML('👥', q ? 'No families match' : 'No families yet', 'Be the first — create one!');
  }catch(e){ showToast(e.message || 'Could not load families', 'error'); }
}
async function openFamily(id){
  openOverlay('screen-family');
  familyState.id = id;
  const body = document.getElementById('family-body');
  body.innerHTML = emptyStateHTML('⏳', 'Loading…', '');
  let f;
  try{ f = await Api.getFamily(id); }
  catch(e){ body.innerHTML = emptyStateHTML('⚠️', 'Could not load family', escapeHTML(e.message || '')); return; }
  familyState.data = f;
  document.getElementById('family-title').textContent = f.name;
  const inAny = !!(STATE.currentUser && STATE.currentUser.family);
  const action = f.my_role
    ? `<button type="button" class="btn btn-glass btn-sm" data-fam-action="leave">${ic('log-out')} Leave</button>`
    : (!inAny && f.members < f.max_members ? `<button type="button" class="btn btn-primary btn-sm" data-fam-action="join">${ic('user-plus')} Join family</button>` : '');
  body.innerHTML = `
    <div class="fam-hero">
      ${emblemHTML(f.emblem, 'xl')}
      <div class="fam-hero-name">${escapeHTML(f.name)} <span class="bdg fam">${escapeHTML(f.tag)}</span></div>
      ${f.description ? `<div class="fam-hero-desc">${escapeHTML(f.description)}</div>` : ''}
      <div class="fam-stats">
        <div><b>${Number(f.members)}/${Number(f.max_members)}</b><span>Members</span></div>
        <div><b>${f.rank ? '#' + Number(f.rank) : '—'}</b><span>This week</span></div>
        <div><b>${escapeHTML(formatScore(f.score))}</b><span>Gift coins</span></div>
      </div>
      <div class="fam-actions">${action}</div>
    </div>
    <div class="seg-tabs" id="fam-tabs">
      <button type="button" data-fam-tab="members">Members</button>
      ${f.my_role ? '<button type="button" data-fam-tab="chat">Chat</button>' : ''}
      <button type="button" data-fam-tab="rooms">Live rooms${f.live_rooms.length ? ` · ${f.live_rooms.length}` : ''}</button>
    </div>
    <div id="fam-tab-body"></div>`;
  renderFamilyTab(familyState.tab === 'chat' && !f.my_role ? 'members' : familyState.tab);
}
function renderFamilyTab(tab){
  familyState.tab = tab;
  const f = familyState.data;
  document.querySelectorAll('#fam-tabs [data-fam-tab]').forEach(b => b.classList.toggle('active', b.dataset.famTab === tab));
  const el = document.getElementById('fam-tab-body');
  if(tab === 'members'){
    const canManage = f.my_role === 'owner' || f.my_role === 'elder';
    el.innerHTML = f.members_list.map(m => {
      const me = STATE.currentUser && m.user.id === STATE.currentUser.id;
      let tools = '';
      if(!me && f.my_role === 'owner' && m.role !== 'owner'){
        tools += `<button type="button" class="store-btn ghost" data-fam-role="${Number(m.user.id)}" data-role="${m.role === 'elder' ? 'member' : 'elder'}">${m.role === 'elder' ? 'Make member' : 'Make elder'}</button>`;
      }
      if(!me && canManage && m.role === 'member' || (!me && f.my_role === 'owner' && m.role === 'elder')){
        tools += `<button type="button" class="store-btn ghost danger" data-fam-kick="${Number(m.user.id)}" aria-label="Remove">${ic('user-minus')}</button>`;
      }
      return userRowHTML(m.user, `<span class="role-chip r-${escapeAttr(m.role)}">${escapeHTML(m.role)}</span>${tools}`, `data-soc-user="${escapeAttr(m.user.username)}"`);
    }).join('');
  } else if(tab === 'rooms'){
    el.innerHTML = f.live_rooms.length ? f.live_rooms.map(r => `
      <button type="button" class="fam-room" data-join-room="${Number(r.id)}">
        <img class="avatar" src="${imgSrc(r.host.avatar_url)}" alt=""><span><b>${escapeHTML(r.name)}</b><span>by ${escapeHTML(r.host.username)}</span></span>
        <span class="rr-live"><span class="badge-live-dot"></span>LIVE</span></button>`).join('')
      : emptyStateHTML('🎙️', 'Nobody is live right now', 'Start a room — your family gets your badge in it.');
  } else {
    el.innerHTML = `<div class="fam-chat" id="fam-chat">${emptyStateHTML('⏳', 'Loading…', '')}</div>
      <form class="fam-chat-bar" id="fam-chat-form"><div class="input-wrap"><input type="text" id="fam-chat-input" maxlength="300" placeholder="Message your family"></div>
      <button type="submit" class="send-btn" aria-label="Send">${ic('send-horizontal')}</button></form>`;
    Api.familyChat(f.id).then(rows => {
      const box = document.getElementById('fam-chat');
      if(!box) return;
      box.innerHTML = rows.length ? rows.map(familyMsgHTML).join('') : emptyStateHTML('💬', 'Say hi to your family', '');
      box.scrollTop = box.scrollHeight;
    }).catch(e => showToast(e.message || 'Could not load chat', 'error'));
  }
}
function familyMsgHTML(m){
  const mine = STATE.currentUser && m.user && m.user.id === STATE.currentUser.id;
  return `<div class="fam-msg ${mine ? 'me' : ''}">${m.user ? `<img class="avatar" src="${imgSrc(m.user.avatar_url)}" alt="">` : ''}
    <div><div class="fam-msg-head">${escapeHTML(m.user ? m.user.username : 'Vibra')} <span>${escapeHTML(timeAgo(m.created_at))}</span></div>
    <div class="fam-msg-text">${escapeHTML(m.text)}</div></div></div>`;
}
function onFamilyMessage(ev){
  if(familyState.id !== ev.family_id || familyState.tab !== 'chat') return;
  const box = document.getElementById('fam-chat');
  if(!box) return;
  if(box.querySelector('.empty-state')) box.innerHTML = '';
  box.insertAdjacentHTML('beforeend', familyMsgHTML(ev.message));
  box.scrollTop = box.scrollHeight;
}
async function familyDo(action, body, ok){
  try{
    await Api.familyAction(familyState.id, action, body);
    if(ok) showToast(ok, 'success');
    await refreshMe();
    if(action === 'leave'){ renderFamilyBrowse(); return; }
    openFamily(familyState.id);
  }catch(e){ showToast(e.message || 'Could not do that', 'error'); }
}
function openCreateFamily(){
  document.getElementById('fc-name').value = '';
  document.getElementById('fc-tag').value = '';
  document.getElementById('fc-desc').value = '';
  STATE.famEmblem = 'crown';
  renderEmblemPicker();
  openModal('family-create-modal');
}
function renderEmblemPicker(){
  document.getElementById('fc-emblems').innerHTML = FAMILY_EMBLEMS.map(k =>
    `<button type="button" class="emblem-opt ${STATE.famEmblem === k ? 'on' : ''}" data-emblem="${k}" aria-label="${k}">${emblemHTML(k)}</button>`).join('');
}
async function createFamily(){
  const btn = document.getElementById('fc-save');
  btn.disabled = true;
  try{
    const f = await Api.createFamily({
      name: document.getElementById('fc-name').value.trim(), tag: document.getElementById('fc-tag').value.trim(),
      emblem: STATE.famEmblem, description: document.getElementById('fc-desc').value.trim(),
    });
    closeModal('family-create-modal');
    await refreshMe();
    showToast(`${f.name} is born! 🎉`, 'success');
    openFamily(f.id);
  }catch(e){ showToast(e.message || 'Could not create family', 'error'); }
  finally{ btn.disabled = false; }
}

/* ---------------------------------------------------------------- bonds: CP & best friends */
const BOND_LABEL = { cp: { icon: '💞', name: 'CP', ask: '💍 Be my CP', gift: 'CP ring' }, bff: { icon: '🤝', name: 'Best friend', ask: '🤝 Best friend', gift: 'friendship bracelet' } };
function bondCardHTML(owner, b){
  if(b.kind === 'cp'){
    return `<div class="cp-card"><img class="avatar" src="${imgSrc(owner.avatar_url)}" alt=""><span class="cp-heart">💞</span>
      <img class="avatar" src="${imgSrc(b.user.avatar_url)}" alt="" data-soc-user="${escapeAttr(b.user.username)}">
      <div class="cp-text"><b>CP</b><span>with ${escapeHTML(b.user.username)}</span></div></div>`;
  }
  return '';
}
// Fills the bond area on someone's profile page.
async function loadBondZone(userId, username, avatar){
  const zone = document.querySelector(`[data-bond-zone="${Number(userId)}"]`);
  if(!zone) return;
  let d;
  try{ d = await Api.bondsOf(userId); }catch(e){ zone.innerHTML = ''; return; }
  const owner = { avatar_url: avatar, username };
  const cp = d.bonds.find(b => b.kind === 'cp');
  const bffs = d.bonds.filter(b => b.kind === 'bff');
  const self = STATE.currentUser && STATE.currentUser.id === userId;
  let actions = '';
  if(!self){
    if(d.with_me) actions = `<div class="bond-state">${BOND_LABEL[d.with_me].icon} You are ${d.with_me === 'cp' ? 'CPs' : 'best friends'}</div>`;
    else if(d.pending_with_me) actions = d.pending_with_me.from_me
      ? `<div class="bond-state">Request sent ${BOND_LABEL[d.pending_with_me.kind].icon} <button type="button" class="store-btn ghost" data-bond-req="${Number(d.pending_with_me.id)}" data-bond-act="cancel">Cancel</button></div>`
      : `<div class="bond-state">${BOND_LABEL[d.pending_with_me.kind].icon} Wants to bond with you <button type="button" class="store-btn buy" data-bond-req="${Number(d.pending_with_me.id)}" data-bond-act="accept">Accept</button><button type="button" class="store-btn ghost" data-bond-req="${Number(d.pending_with_me.id)}" data-bond-act="decline">Decline</button></div>`;
    else actions = `<div class="bond-asks">
      ${cp || (STATE.currentUser && STATE.currentUser.cp) ? '' : `<button type="button" class="bond-ask cp" data-bond-ask="cp" data-user="${Number(userId)}" data-name="${escapeAttr(username)}">💍 Be my CP <span>${ic('coins')}${Number(d.costs.cp).toLocaleString()}</span></button>`}
      <button type="button" class="bond-ask bff" data-bond-ask="bff" data-user="${Number(userId)}" data-name="${escapeAttr(username)}">🤝 Best friend <span>${ic('coins')}${Number(d.costs.bff).toLocaleString()}</span></button></div>`;
  }
  zone.innerHTML = `${cp ? bondCardHTML(owner, cp) : ''}
    ${bffs.length ? `<div class="bff-row"><span class="bff-label">🤝 Best friends</span>${bffs.map(b => `<img class="avatar" src="${imgSrc(b.user.avatar_url)}" alt="${escapeAttr(b.user.username)}" title="${escapeAttr(b.user.username)}" data-soc-user="${escapeAttr(b.user.username)}">`).join('')}</div>` : ''}
    ${actions}`;
}
let pendingBondAsk = null;
function askBond(kind, userId, name){
  pendingBondAsk = { kind, userId, name };
  const cost = kind === 'cp' ? 5200 : 1314;
  const admin = STATE.currentUser && STATE.currentUser.is_admin;
  document.getElementById('bond-title').textContent = kind === 'cp' ? `Ask ${name} to be your CP?` : `Ask ${name} to be your best friend?`;
  document.getElementById('bond-desc').innerHTML = `You send a ${BOND_LABEL[kind].gift} (${admin ? 'free for admin' : `${ic('coins')} ${cost.toLocaleString()} coins`}). If they say no, you get the coins back.`;
  document.getElementById('bond-emoji').textContent = kind === 'cp' ? '💍' : '🤝';
  openModal('bond-modal');
}
async function confirmBond(){
  const a = pendingBondAsk;
  if(!a) return;
  const btn = document.getElementById('bond-confirm');
  btn.disabled = true;
  try{
    const res = await Api.requestBond(a.userId, a.kind);
    if(res.balance != null){ STATE.walletBalance = res.balance; updateWalletUI(); }
    closeModal('bond-modal');
    showToast(`Request sent to ${a.name}`, 'success');
    loadBondZone(a.userId, a.name, (document.querySelector('#user-profile-target img.avatar') || {}).src);
  }catch(e){ showToast(e.message || 'Could not send request', 'error'); }
  finally{ btn.disabled = false; }
}
async function bondRequestAction(reqId, act){
  try{
    await Api.answerBond(reqId, act);
    showToast(act === 'accept' ? 'Bond made! 💞' : act === 'decline' ? 'Request declined' : 'Request cancelled — coins refunded', act === 'accept' ? 'success' : 'info');
    await refreshMe(); refreshWallet().then(() => updateWalletUI());
    if(document.getElementById('screen-bonds').classList.contains('active')) openBonds();
    const zone = document.querySelector('[data-bond-zone]');
    if(zone) loadBondZone(Number(zone.dataset.bondZone), zone.dataset.name, zone.dataset.avatar);
  }catch(e){ showToast(e.message || 'Could not do that', 'error'); }
}
async function openBonds(){
  openOverlay('screen-bonds');
  const body = document.getElementById('bonds-body');
  body.innerHTML = emptyStateHTML('⏳', 'Loading…', '');
  let d;
  try{ d = await Api.getBonds(); }catch(e){ body.innerHTML = emptyStateHTML('⚠️', 'Could not load', ''); return; }
  const req = (r, mine) => userRowHTML(r.user, mine
    ? `<span class="role-chip">${BOND_LABEL[r.kind].icon} sent</span><button type="button" class="store-btn ghost" data-bond-req="${Number(r.id)}" data-bond-act="cancel">Cancel</button>`
    : `<button type="button" class="store-btn buy" data-bond-req="${Number(r.id)}" data-bond-act="accept">${BOND_LABEL[r.kind].icon} Accept</button><button type="button" class="store-btn ghost" data-bond-req="${Number(r.id)}" data-bond-act="decline">${ic('x')}</button>`);
  body.innerHTML = `
    ${d.incoming.length ? `<div class="rs-label">Requests for you</div>${d.incoming.map(r => req(r, false)).join('')}` : ''}
    <div class="rs-label">Your bonds</div>
    ${d.bonds.length ? d.bonds.map(b => userRowHTML(b.user, `<span class="role-chip">${BOND_LABEL[b.kind].icon} ${BOND_LABEL[b.kind].name}</span><button type="button" class="store-btn ghost" data-bond-break="${Number(b.user.id)}" data-name="${escapeAttr(b.user.username)}">End</button>`, `data-soc-user="${escapeAttr(b.user.username)}"`)).join('')
      : emptyStateHTML('💞', 'No bonds yet', `Open someone's profile and ask them to be your CP or best friend (up to ${Number(d.max_bff)}).`)}
    ${d.outgoing.length ? `<div class="rs-label">Waiting for an answer</div>${d.outgoing.map(r => req(r, true)).join('')}` : ''}`;
}

/* ---------------------------------------------------------------- visitors */
async function openVisitors(){
  openOverlay('screen-visitors');
  const body = document.getElementById('visitors-body');
  body.innerHTML = emptyStateHTML('⏳', 'Loading…', '');
  try{
    const d = await Api.getVisitors();
    body.innerHTML = d.visitors.length ? d.visitors.map(v => userRowHTML(v.user,
      `<span class="visit-meta">${v.is_new ? '<span class="new-dot">NEW</span>' : ''}${Number(v.count) > 1 ? `${Number(v.count)}× · ` : ''}${escapeHTML(timeAgo(v.last_at))}</span>`,
      `data-soc-user="${escapeAttr(v.user.username)}"`)).join('')
      : emptyStateHTML('👀', 'No visitors yet', 'Join rooms and chat — people will check out your profile.');
    if(d.new){ await Api.markVisitorsSeen(); if(STATE.currentUser) STATE.currentUser.new_visitors = 0; }
  }catch(e){ body.innerHTML = emptyStateHTML('⚠️', 'Could not load visitors', ''); }
}

/* ---------------------------------------------------------------- friends in rooms (home) */
async function renderFriendsLive(){
  const row = document.getElementById('stories-row');
  const section = row && row.closest('.section');
  if(!section) return;
  let rows = [];
  try{ rows = await Api.friendsLive(); }catch(e){ rows = []; }
  if(!rows.length){ section.classList.add('hidden'); row.innerHTML = ''; return; }
  section.classList.remove('hidden');
  const h = section.querySelector('.section-head h2');
  if(h) h.textContent = 'Friends in rooms';
  row.innerHTML = rows.map(r => `
    <div class="story" data-join-room="${Number(r.room.id)}" title="${escapeAttr(r.room.name)}">
      <div class="vibra-ring speaking"><img class="avatar" src="${imgSrc(r.user.avatar_url)}" alt=""><span class="online-dot"></span></div>
      <span>${escapeHTML(r.user.username)}</span><span class="story-room">${escapeHTML(r.room.name)}</span>
    </div>`).join('');
}

/* ---------------------------------------------------------------- scheduled rooms */
function whenLabel(iso){
  const d = new Date(iso), now = new Date();
  const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
  const time = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if(d.toDateString() === now.toDateString()) return `Today ${time}`;
  if(d.toDateString() === tomorrow.toDateString()) return `Tomorrow ${time}`;
  return `${d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} ${time}`;
}
async function renderUpcoming(){
  const section = document.getElementById('upcoming-section');
  if(!section || VIBRA_CONFIG.DEMO_DATA) return;
  let rows = [];
  try{ rows = await Api.listScheduled('all'); }catch(e){ rows = []; }
  section.hidden = !rows.length;
  document.getElementById('upcoming-row').innerHTML = rows.map(s => {
    const soon = new Date(s.starts_at).getTime() - Date.now() <= 15 * 60000;
    const btn = s.is_mine
      ? `<button type="button" class="store-btn buy" data-sched-start="${Number(s.id)}" ${soon ? '' : 'disabled'}>${ic('radio')} Go live</button>
         <button type="button" class="store-btn ghost" data-sched-cancel="${Number(s.id)}" aria-label="Cancel">${ic('x')}</button>`
      : `<button type="button" class="store-btn ${s.reminded ? 'ghost on' : 'buy'}" data-sched-remind="${Number(s.id)}">${ic(s.reminded ? 'bell-ring' : 'bell')} ${s.reminded ? 'Reminded' : 'Remind me'}</button>`;
    return `<div class="up-card">
      <div class="up-when">${ic('calendar-clock')} ${escapeHTML(whenLabel(s.starts_at))}</div>
      <div class="up-title">${escapeHTML(s.title)}</div>
      <div class="up-host"><img class="avatar" src="${imgSrc(s.host.avatar_url)}" alt=""><span>${escapeHTML(s.host.username)}</span><span class="rr-cat">${escapeHTML(s.category)}</span></div>
      <div class="up-foot"><span class="up-count">${ic('users')} ${Number(s.reminders)}</span>${btn}</div>
    </div>`;
  }).join('');
}
async function scheduledDo(id, action){
  try{
    const res = await Api.scheduledAction(id, action);
    if(action === 'start'){ await refreshApiRooms(); openRoom(res.room_id); }
    else if(action === 'remind') showToast(res.reminded ? "We'll remind you when it starts" : 'Reminder removed', 'success');
    else showToast('Scheduled room cancelled', 'info');
    renderUpcoming();
  }catch(e){ showToast(e.message || 'Could not do that', 'error'); }
}

/* ---------------------------------------------------------------- stickers */
const STICKERS = {
  hi: '👋', love: '😍', lol: '🤣', wow: '😮', cry: '😭', clap: '👏',
  fire: '🔥', party: '🥳', cool: '😎', sleepy: '😴', angry: '😤', gift: '🎁',
};
// "[sticker:key]" -> big animated sticker, only for whitelisted keys.
function stickerHTML(text){
  const m = /^\[sticker:([a-z]+)\]$/.exec(String(text || '').trim());
  return m && STICKERS[m[1]] ? `<div class="sticker st-${m[1]}" role="img" aria-label="${m[1]} sticker">${STICKERS[m[1]]}</div>` : '';
}
function stickerStripHTML(){
  return `<div class="sticker-strip"><div class="sticker-label">Stickers</div>${Object.entries(STICKERS).map(([k, e]) =>
    `<button type="button" class="sticker-pick" data-sticker="${k}" aria-label="${k} sticker">${e}</button>`).join('')}</div>`;
}
function sendSticker(where, key){
  const text = `[sticker:${key}]`;
  if(where === 'room' && STATE.activeRoom && typeof STATE.activeRoom.id === 'number'){
    document.getElementById('emoji-picker').classList.remove('show');
    Api.sendMessage(STATE.activeRoom.id, text).catch(e => showToast(e.message || 'Could not send', 'error'));
  } else if(where === 'dm' && typeof STATE.activeDM === 'number'){
    document.getElementById('dm-emoji-picker').classList.remove('show');
    const to = STATE.activeDM;
    Api.sendDirectMessage(to, text).then(msg => {
      (dmThreads[to] = dmThreads[to] || []).push(dmFromApi(msg));
      if(STATE.activeDM === to) renderDMBody();
    }).catch(e => showToast(e.message || 'Could not send', 'error'));
  }
}

/* ---------------------------------------------------------------- voice messages */
function voiceSrc(v){
  if(!v || !v.url) return '';
  const u = String(v.url);
  if(/^\/media\/voice\/[A-Za-z0-9_-]+\.(webm|ogg|mp3|m4a|wav)$/.test(u)){
    try{ return new URL(API_BASE, location.href).origin + u; }catch(e){ return ''; }
  }
  return safeImgUrl(u);
}
function fmtSecs(s){ s = Math.max(0, Math.round(Number(s) || 0)); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`; }
function voiceBubbleHTML(v){
  const src = voiceSrc(v);
  if(!src) return '';
  const bars = Array.from({ length: 16 }, (_, i) => `<i style="height:${6 + ((i * 37 + Number(v.seconds) * 11) % 14)}px"></i>`).join('');
  return `<button type="button" class="voice-msg" data-voice-src="${escapeAttr(src)}" aria-label="Play voice message">
    <span class="vplay">${ic('play')}</span><span class="vwave">${bars}</span><span class="vdur">${escapeHTML(fmtSecs(v.seconds))}</span></button>`;
}
const VoicePlayer = { audio: null, btn: null };
function toggleVoicePlayback(btn){
  if(VoicePlayer.btn === btn && VoicePlayer.audio && !VoicePlayer.audio.paused){
    VoicePlayer.audio.pause(); return;
  }
  if(VoicePlayer.audio){ VoicePlayer.audio.pause(); }
  if(VoicePlayer.btn){ VoicePlayer.btn.classList.remove('playing'); VoicePlayer.btn.querySelector('.vplay').innerHTML = ic('play'); }
  const a = new Audio(btn.dataset.voiceSrc);
  VoicePlayer.audio = a; VoicePlayer.btn = btn;
  const done = () => { btn.classList.remove('playing'); btn.querySelector('.vplay').innerHTML = ic('play'); btn.style.removeProperty('--p'); };
  a.onpause = done; a.onended = done;
  a.ontimeupdate = () => { if(a.duration && isFinite(a.duration)) btn.style.setProperty('--p', `${Math.round(a.currentTime / a.duration * 100)}%`); };
  a.play().then(() => { btn.classList.add('playing'); btn.querySelector('.vplay').innerHTML = ic('pause'); })
    .catch(() => showToast('Could not play this voice message', 'error'));
}
const VoiceRec = {
  rec: null, stream: null, chunks: [], startedAt: 0, timer: null, target: null, cancelled: false,
  pickType(){
    const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'];
    return (window.MediaRecorder && MediaRecorder.isTypeSupported) ? types.find(t => MediaRecorder.isTypeSupported(t)) || '' : '';
  },
  async start(target){
    if(this.rec) return;
    if(!window.MediaRecorder || !navigator.mediaDevices){ showToast('Voice messages are not supported on this browser', 'error'); return; }
    try{ this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }); }
    catch(e){ showToast(typeof micErrorMessage === 'function' ? micErrorMessage(e) : 'Microphone blocked', 'error'); return; }
    const type = this.pickType();
    this.rec = new MediaRecorder(this.stream, type ? { mimeType: type, audioBitsPerSecond: 32000 } : undefined);
    this.chunks = []; this.target = target; this.cancelled = false; this.startedAt = Date.now();
    this.rec.ondataavailable = e => { if(e.data && e.data.size) this.chunks.push(e.data); };
    this.rec.onstop = () => this.finish();
    this.rec.start(250);
    const bar = document.getElementById('voice-rec');
    bar.hidden = false;
    this.tick();
    this.timer = setInterval(() => this.tick(), 250);
  },
  tick(){
    const s = (Date.now() - this.startedAt) / 1000;
    document.getElementById('voice-rec-time').textContent = `${fmtSecs(s)} / 1:00`;
    document.getElementById('voice-rec-bar').style.width = `${Math.min(100, s / 60 * 100)}%`;
    if(s >= 60) this.stop(true);
  },
  stop(send){
    if(!this.rec) return;
    this.cancelled = !send;
    clearInterval(this.timer);
    try{ this.rec.stop(); }catch(e){ this.finish(); }
  },
  async finish(){
    const secs = (Date.now() - this.startedAt) / 1000;
    const blob = new Blob(this.chunks, { type: (this.rec && this.rec.mimeType) || 'audio/webm' });
    const target = this.target, cancelled = this.cancelled;
    if(this.stream) this.stream.getTracks().forEach(t => t.stop());
    Object.assign(this, { rec: null, stream: null, chunks: [], target: null });
    document.getElementById('voice-rec').hidden = true;
    if(cancelled) return;
    if(secs < 1 || !blob.size){ showToast('Hold on a little longer to record', 'info'); return; }
    try{
      const clip = await Api.uploadVoice(blob, Math.min(60, secs));
      if(target === 'room' && STATE.activeRoom && typeof STATE.activeRoom.id === 'number'){
        await Api.sendMessage(STATE.activeRoom.id, '', null, clip.id);
      } else if(target === 'dm' && typeof STATE.activeDM === 'number'){
        const to = STATE.activeDM;
        const msg = await Api.sendDirectMessage(to, '', clip.id);
        (dmThreads[to] = dmThreads[to] || []).push(dmFromApi(msg));
        if(STATE.activeDM === to) renderDMBody();
      }
    }catch(e){ showToast(e.message || 'Could not send voice message', 'error'); }
  },
};

/* ---------------------------------------------------------------- bindings */
function bindSocial(){
  const fam = document.getElementById('family-body');
  fam.addEventListener('click', e => {
    const open = e.target.closest('[data-open-family]');
    if(open) return openFamily(Number(open.dataset.openFamily));
    if(e.target.closest('#family-create-open')) return openCreateFamily();
    const tab = e.target.closest('[data-fam-tab]');
    if(tab) return renderFamilyTab(tab.dataset.famTab);
    const act = e.target.closest('[data-fam-action]');
    if(act){
      const a = act.dataset.famAction;
      if(a === 'leave' && !confirm('Leave this family?')) return;
      return familyDo(a, null, a === 'join' ? `Welcome to ${familyState.data.name}!` : 'You left the family');
    }
    const role = e.target.closest('[data-fam-role]');
    if(role) return familyDo('role', { user_id: Number(role.dataset.famRole), role: role.dataset.role }, 'Role updated');
    const kick = e.target.closest('[data-fam-kick]');
    if(kick){ if(confirm('Remove this member?')) familyDo('kick', { user_id: Number(kick.dataset.famKick) }, 'Member removed'); return; }
    const u = e.target.closest('[data-soc-user]');
    if(u) return openApiProfile(u.dataset.socUser);
  });
  fam.addEventListener('input', e => {
    if(e.target.id !== 'family-search') return;
    clearTimeout(STATE.famSearchT);
    STATE.famSearchT = setTimeout(() => renderFamilyBrowse(e.target.value.trim()), 300);
  });
  fam.addEventListener('submit', async e => {
    if(e.target.id !== 'fam-chat-form') return;
    e.preventDefault();
    const input = document.getElementById('fam-chat-input');
    const text = input.value.trim();
    if(!text) return;
    input.value = '';
    try{ await Api.sendFamilyChat(familyState.id, text); }
    catch(err){ input.value = text; showToast(err.message || 'Could not send', 'error'); }
  });
  document.getElementById('fc-emblems').addEventListener('click', e => {
    const b = e.target.closest('[data-emblem]'); if(!b) return;
    STATE.famEmblem = b.dataset.emblem; renderEmblemPicker();
  });
  document.getElementById('fc-tag').addEventListener('input', e => { e.target.value = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6); });
  document.getElementById('fc-save').addEventListener('click', createFamily);
  document.getElementById('bond-confirm').addEventListener('click', confirmBond);
  document.body.addEventListener('click', e => {
    const ask = e.target.closest('[data-bond-ask]');
    if(ask) return askBond(ask.dataset.bondAsk, Number(ask.dataset.user), ask.dataset.name);
    const req = e.target.closest('[data-bond-req]');
    if(req) return bondRequestAction(Number(req.dataset.bondReq), req.dataset.bondAct);
    const brk = e.target.closest('[data-bond-break]');
    if(brk){
      if(confirm(`End your bond with ${brk.dataset.name}? Coins are not refunded.`))
        Api.breakBond(Number(brk.dataset.bondBreak)).then(() => { showToast('Bond ended', 'info'); refreshMe(); openBonds(); })
          .catch(err => showToast(err.message || 'Could not do that', 'error'));
      return;
    }
    const fam2 = e.target.closest('[data-open-family-chip]');
    if(fam2) return openFamily(Number(fam2.dataset.openFamilyChip));
    const v = e.target.closest('[data-voice-src]');
    if(v) return toggleVoicePlayback(v);
    const st = e.target.closest('[data-sticker]');
    if(st) return sendSticker(st.closest('#dm-emoji-picker') ? 'dm' : 'room', st.dataset.sticker);
    const remind = e.target.closest('[data-sched-remind]');
    if(remind) return scheduledDo(Number(remind.dataset.schedRemind), 'remind');
    const go = e.target.closest('[data-sched-start]');
    if(go) return scheduledDo(Number(go.dataset.schedStart), 'start');
    const cancel = e.target.closest('[data-sched-cancel]');
    if(cancel){ if(confirm('Cancel this scheduled room?')) scheduledDo(Number(cancel.dataset.schedCancel), 'cancel'); return; }
  });
  ['bonds-body', 'visitors-body'].forEach(id => document.getElementById(id).addEventListener('click', e => {
    if(e.target.closest('button')) return;
    const u = e.target.closest('[data-soc-user]'); if(u) openApiProfile(u.dataset.socUser);
  }));
  // voice recording
  document.getElementById('dm-voice-btn').addEventListener('click', () => VoiceRec.start('dm'));
  document.getElementById('chat-voice-btn').addEventListener('click', () => VoiceRec.start('room'));
  document.getElementById('voice-rec-send').addEventListener('click', () => VoiceRec.stop(true));
  document.getElementById('voice-rec-cancel').addEventListener('click', () => VoiceRec.stop(false));
  // stickers inside both emoji pickers
  ['emoji-picker', 'dm-emoji-picker'].forEach(id => document.getElementById(id).insertAdjacentHTML('beforeend', stickerStripHTML()));
}
