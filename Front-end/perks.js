/* ============================================================================
   perks.js — status & engagement (phases 2 and 3)
   Levels/VIP badges, avatar frames, the store (frames + mounts), leaderboards,
   daily check-in, daily tasks, edit-profile with photo upload, home banners.
   Relies on app.js helpers at call time (ic, escapeHTML, imgSrc, showToast,
   openOverlay/closeOverlay, openModal/closeModal, STATE, Api).
   ============================================================================ */
const FRAME_KEYS = ['neon', 'rose', 'ice', 'gold', 'flame', 'galaxy'];
const MOUNTS = {
  bike: { emoji: '🏍️', name: 'Street Bike' }, car: { emoji: '🏎️', name: 'Supercar' },
  rocket: { emoji: '🚀', name: 'Rocket' }, unicorn: { emoji: '🦄', name: 'Unicorn' },
  ufo: { emoji: '🛸', name: 'UFO' }, dragon: { emoji: '🐉', name: 'Dragon' },
};
const VIP_PERKS = [
  'VIP badge next to your name',
  'Golden entry banner when you join a room',
  'Coloured name in chat and on seats',
  'Glowing chat bubbles',
  'Animated shimmering name',
];

// Whitelisted, so a key from the server can never inject a class name.
function frameClass(key){ return FRAME_KEYS.includes(key) ? ` frame frame-${key}` : ''; }
function vipNameClass(vip){ const v = Math.min(5, Number(vip) || 0); return v ? ` vip-name vip-${v}` : ''; }
function badgesHTML(u){
  if(!u) return '';
  const wealth = Number(u.wealth_level != null ? u.wealth_level : u.level) || 1;
  const charm = Number(u.charm_level != null ? u.charm_level : u.charm) || 0;
  const vip = Math.min(5, Number(u.vip) || 0);
  return (u.is_admin ? `<span class="bdg admin" title="Vibra admin">ADMIN</span>` : '')
    + `<span class="bdg wealth" title="Wealth level">${ic('gem')}${wealth}</span>`
    + (charm > 1 ? `<span class="bdg charm" title="Charm level">${ic('heart')}${charm}</span>` : '')
    + (vip ? `<span class="bdg vip vip-${vip}" title="VIP ${vip}">VIP${vip}</span>` : '');
}

/* ---------------------------------------------------------------- refresh me */
async function refreshMe(){
  if(VIBRA_CONFIG.DEMO_DATA || !STATE.currentUser) return;
  try{
    const p = await Api.me();
    STATE.currentUser = profileToAccount(p);
    const mini = document.getElementById('mini-avatar');
    if(mini) mini.src = safeImgUrl(STATE.currentUser.avatar);
    const prof = document.getElementById('tab-profile');
    if(prof && !prof.classList.contains('hidden')) renderOwnProfile();
  }catch(e){ console.error('Could not refresh profile', e); }
}

/* ---------------------------------------------------------------- store */
let storeItems = [];
async function openStore(tab){
  STATE.storeTab = tab || STATE.storeTab || 'frame';
  openOverlay('screen-store');
  document.getElementById('store-grid').innerHTML = emptyStateHTML('⏳', 'Loading…', '');
  await refreshWallet();
  document.getElementById('store-balance').textContent = getWallet().toLocaleString();
  try{ storeItems = await Api.getStore(); }
  catch(e){ document.getElementById('store-grid').innerHTML = emptyStateHTML('⚠️', 'Could not load the store', escapeHTML(e.message || '')); return; }
  renderStore();
}
function daysLeft(iso){
  const ms = new Date(iso).getTime() - Date.now();
  if(ms <= 0) return '';
  if(ms > 3650 * 86400000) return 'Forever';
  const d = Math.floor(ms / 86400000), h = Math.floor(ms / 3600000) % 24;
  return d > 0 ? `${d}d ${h}h left` : `${h || 1}h left`;
}
function renderStore(){
  const tab = STATE.storeTab;
  document.querySelectorAll('#store-tabs [data-store-tab]').forEach(b => b.classList.toggle('active', b.dataset.storeTab === tab));
  const me = STATE.currentUser || {};
  const worn = storeItems.find(i => i.kind === tab && i.equipped);
  const prev = document.getElementById('store-preview');
  document.getElementById('store-admin-note').hidden = !storeItems.some(i => i.free_for_admin);
  if(tab === 'theme'){
    const room = STATE.activeRoom;
    const cur = room && STATE.isHost ? (room.theme || '') : null;
    prev.innerHTML = `<div class="theme-swatch t-${cur ? escapeAttr(cur) : 'starry'}"></div>
      <div class="store-preview-t">${cur !== null ? `Your room uses <b>${escapeHTML((ROOM_THEMES[cur] || ROOM_THEMES['']).name)}</b>` : 'Themes change your room\'s background for everyone'}</div>`;
  } else if(tab === 'frame'){
    prev.innerHTML = `<div class="avatar-wrap${frameClass(worn && worn.key)}"><img class="avatar" src="${imgSrc(me.avatar)}" alt=""></div>
      <div class="store-preview-t">${worn ? `Wearing <b>${escapeHTML(worn.name)}</b>` : 'No frame on'}</div>`;
  } else {
    const m = worn && MOUNTS[worn.key];
    prev.innerHTML = `<div class="mount-chip">${m ? escapeHTML(m.emoji) : ic('car')}</div>
      <div class="store-preview-t">${worn ? `Riding <b>${escapeHTML(worn.name)}</b>` : 'No mount — you walk in'}</div>`;
  }
  const items = storeItems.filter(i => i.kind === tab);
  document.getElementById('store-grid').innerHTML = items.map(i => {
    const owned = !!i.owned_until;
    const visual = tab === 'theme'
      ? `<div class="theme-swatch t-${ROOM_THEMES[i.key] ? escapeAttr(i.key) : 'starry'}"></div>`
      : tab === 'frame'
      ? `<div class="avatar-wrap sm${frameClass(i.key)}"><img class="avatar" src="${imgSrc(me.avatar)}" alt=""></div>`
      : `<button type="button" class="mount-thumb" data-preview-mount="${escapeAttr(i.key)}" aria-label="Preview">${escapeHTML((MOUNTS[i.key] || {}).emoji || '🚗')}<span>${ic('play')}</span></button>`;
    const action = tab === 'theme'
      ? (owned ? `<button type="button" class="store-btn" data-apply-theme="${escapeAttr(i.key)}">${STATE.activeRoom && STATE.isHost ? 'Use in room' : 'Owned'}</button>`
               : `<button type="button" class="store-btn buy" data-buy="${Number(i.id)}">${ic('coins')} ${Number(i.price).toLocaleString()}</button>`)
      : i.equipped
      ? `<button type="button" class="store-btn ghost" data-unequip="${escapeAttr(i.kind)}">Take off</button>`
      : owned ? `<button type="button" class="store-btn" data-equip="${Number(i.id)}">Use</button>`
              : `<button type="button" class="store-btn buy" data-buy="${Number(i.id)}">${ic('coins')} ${Number(i.price).toLocaleString()}</button>`;
    return `<div class="store-card${i.equipped ? ' on' : ''}">
      ${visual}
      <div class="nm">${escapeHTML(i.name)}</div>
      <div class="meta">${owned ? escapeHTML(daysLeft(i.owned_until)) + (i.equipped ? ' · in use' : '') : `${Number(i.days)} days`}</div>
      ${action}${owned && !i.equipped && !i.free_for_admin ? `<button type="button" class="store-renew" data-buy="${Number(i.id)}">Renew ${ic('coins')}${Number(i.price).toLocaleString()}</button>` : ''}
    </div>`;
  }).join('') || emptyStateHTML('🛍️', 'Nothing here yet', '');
}
async function storeAction(fn, okMsg){
  try{
    const res = await fn();
    if(res && res.balance != null){ STATE.walletBalance = res.balance; updateWalletUI(); }
    storeItems = await Api.getStore();
    await refreshWallet();
    document.getElementById('store-balance').textContent = getWallet().toLocaleString();
    renderStore();
    refreshMe();
    if(okMsg) showToast(okMsg, 'success');
  }catch(e){ showToast(e.message || 'Something went wrong', 'error'); }
}

/* ---------------------------------------------------------------- levels & VIP */
function levelCard(kind, data){
  const label = kind === 'wealth' ? 'Wealth level' : 'Charm level';
  const hint = kind === 'wealth' ? 'Coins you send in gifts' : 'Coins you receive in gifts';
  const end = data.next_level_at;
  const pct = end ? Math.max(2, Math.min(100, Math.round((data.xp - data.level_start) / (end - data.level_start) * 100))) : 100;
  return `<div class="lvl-card ${kind}">
    <div class="lvl-top"><span class="lvl-ic">${ic(kind === 'wealth' ? 'gem' : 'heart')}</span>
      <div><div class="lvl-t">${label}</div><div class="lvl-h">${hint}</div></div>
      <div class="lvl-n">Lv ${Number(data.level)}</div></div>
    <div class="lvl-bar"><span style="width:${pct}%"></span></div>
    <div class="lvl-foot">${Number(data.xp).toLocaleString()} xp${end ? ` · ${Number(end - data.xp).toLocaleString()} to Lv ${Number(data.level) + 1}` : ' · max level'}</div>
  </div>`;
}
async function openLevels(){
  openOverlay('screen-levels');
  const body = document.getElementById('levels-body');
  body.innerHTML = emptyStateHTML('⏳', 'Loading…', '');
  try{
    const p = await Api.me();
    const v = p.vip;
    const nxt = v.next_tier_at;
    const pct = nxt ? Math.max(2, Math.min(100, Math.round(v.spent / nxt * 100))) : 100;
    body.innerHTML = `
      ${levelCard('wealth', p.wealth)}
      ${levelCard('charm', p.charm)}
      <div class="vip-card t${Math.min(5, v.tier)}">
        <div class="vip-head"><div class="vip-crest">${ic('crown')}</div>
          <div><div class="vip-t">${v.tier ? `VIP ${v.tier}` : 'Not VIP yet'}</div>
          <div class="vip-h">${nxt ? `Send ${Number(nxt - v.spent).toLocaleString()} more coins in gifts to reach VIP ${v.tier + 1}` : 'Top tier reached'}</div></div></div>
        <div class="lvl-bar gold"><span style="width:${pct}%"></span></div>
        <div class="vip-tiers">${v.tiers.map(t => `
          <div class="vip-tier${t.tier <= v.tier ? ' got' : ''}"><b>VIP ${t.tier}</b><span>${Number(t.needs).toLocaleString()} coins</span><em>${escapeHTML(VIP_PERKS[t.tier - 1])}</em></div>`).join('')}
        </div>
      </div>`;
  }catch(e){ body.innerHTML = emptyStateHTML('⚠️', 'Could not load levels', escapeHTML(e.message || '')); }
}

/* ---------------------------------------------------------------- leaderboards */
async function openLeaderboard(board, period){
  STATE.lbBoard = board || STATE.lbBoard || 'rich';
  STATE.lbPeriod = period || STATE.lbPeriod || 'week';
  openOverlay('screen-leaderboard');
  document.querySelectorAll('#lb-boards [data-lb-board]').forEach(b => b.classList.toggle('active', b.dataset.lbBoard === STATE.lbBoard));
  document.querySelectorAll('#lb-periods [data-lb-period]').forEach(b => b.classList.toggle('active', b.dataset.lbPeriod === STATE.lbPeriod));
  const body = document.getElementById('lb-body');
  body.innerHTML = emptyStateHTML('⏳', 'Loading…', '');
  let rows;
  try{ rows = await Api.getLeaderboard(STATE.lbBoard, STATE.lbPeriod); }
  catch(e){ body.innerHTML = emptyStateHTML('⚠️', 'Could not load rankings', escapeHTML(e.message || '')); return; }
  if(!rows.length){ body.innerHTML = emptyStateHTML('🏆', 'No gifts yet in this period', 'Send a gift in any room to get on the board.'); return; }
  const who = (r) => r.room
    ? { name: r.room.name, avatar: r.room.host.avatar_url, frame: r.room.host.frame, sub: `by ${r.room.host.username}`, roomId: r.room.id }
    : { name: r.user.username, avatar: r.user.avatar_url, frame: r.user.frame, user: r.user };
  const podium = rows.slice(0, 3);
  const order = [podium[1], podium[0], podium[2]].filter(Boolean);
  body.innerHTML = `<div class="lb-podium">${order.map(r => { const w = who(r); return `
      <div class="lb-pod p${r.rank}"${w.roomId ? ` data-lb-room="${Number(w.roomId)}"` : ''}>
        <div class="lb-crown">${r.rank === 1 ? ic('crown') : r.rank}</div>
        <div class="avatar-wrap${frameClass(w.frame)}"><img class="avatar" src="${imgSrc(w.avatar)}" alt=""></div>
        <div class="lb-name">${escapeHTML(w.name)}</div>
        <div class="lb-score">${ic('coins')}${escapeHTML(formatScore(r.score))}</div>
      </div>`; }).join('')}</div>
    <div class="lb-list">${rows.slice(3).map(r => { const w = who(r); return `
      <div class="lb-row"${w.roomId ? ` data-lb-room="${Number(w.roomId)}"` : ''}>
        <span class="lb-rank">${r.rank}</span>
        <img class="avatar" src="${imgSrc(w.avatar)}" alt="">
        <div class="lb-meta"><div class="lb-name">${escapeHTML(w.name)}</div>${w.user ? `<div class="lb-bdg">${badgesHTML(w.user)}</div>` : `<div class="lb-sub">${escapeHTML(w.sub)}</div>`}</div>
        <span class="lb-score">${ic('coins')}${escapeHTML(formatScore(r.score))}</span>
      </div>`; }).join('')}</div>`;
}

/* ---------------------------------------------------------------- daily check-in */
let checkinShownOn = '';
function renderCheckin(st){
  const body = document.getElementById('checkin-body');
  const today = st.claimed_today ? st.streak : st.today_day;
  body.innerHTML = `<div class="ck-days">${st.rewards.map((c, i) => {
      const day = i + 1;
      const got = st.claimed_today ? day <= st.streak : day < today;
      const now = !st.claimed_today && day === today;
      return `<div class="ck-day${got ? ' got' : ''}${now ? ' now' : ''}${day === 7 ? ' big' : ''}">
        <span class="d">Day ${day}</span><span class="c">${ic('coins')}</span><span class="v">${c}</span>${got ? `<span class="ok">${ic('check')}</span>` : ''}</div>`;
    }).join('')}</div>
    <button type="button" class="ck-claim" id="checkin-claim" ${st.claimed_today ? 'disabled' : ''}>
      ${st.claimed_today ? 'Come back tomorrow' : `Claim ${st.rewards[today - 1]} coins`}</button>`;
}
async function maybeShowCheckin(force){
  if(VIBRA_CONFIG.DEMO_DATA || !STATE.currentUser) return;
  const key = new Date().toDateString() + ':' + STATE.currentUser.id;
  if(!force && checkinShownOn === key) return;
  try{
    const st = await Api.getCheckin();
    if(st.claimed_today && !force) return;
    checkinShownOn = key;
    renderCheckin(st);
    openModal('checkin-modal');
  }catch(e){ console.error('check-in status failed', e); }
}
async function claimCheckin(){
  const btn = document.getElementById('checkin-claim');
  if(btn) btn.disabled = true;
  try{
    const res = await Api.claimCheckin();
    STATE.walletBalance = res.balance; updateWalletUI();
    if(btn) FX.burstAt(btn, 60);
    showToast(`+${res.coins} coins — day ${res.day} collected!`, 'success');
    renderCheckin(await Api.getCheckin());
    setTimeout(() => closeModal('checkin-modal'), 1400);
  }catch(e){ showToast(e.message || 'Could not claim', 'error'); if(btn) btn.disabled = false; }
}

/* ---------------------------------------------------------------- tasks */
async function openTasks(){
  openOverlay('screen-tasks');
  const body = document.getElementById('tasks-body');
  body.innerHTML = emptyStateHTML('⏳', 'Loading…', '');
  try{
    const [tasks, ck] = await Promise.all([Api.getTasks(), Api.getCheckin()]);
    body.innerHTML = `
      <button type="button" class="task-ck" id="tasks-open-checkin">
        <span class="lvl-ic">${ic('calendar-check')}</span>
        <div><b>Daily check-in</b><span>${ck.claimed_today ? `Day ${ck.streak} collected — see you tomorrow` : `Day ${ck.today_day} reward is waiting`}</span></div>
        ${ic('chevron-right')}</button>
      ${tasks.map(t => `<div class="task-row${t.claimed ? ' claimed' : ''}">
        <div class="task-meta"><div class="task-t">${escapeHTML(t.title)}</div>
          <div class="lvl-bar"><span style="width:${Math.round(t.progress / t.goal * 100)}%"></span></div>
          <div class="task-p">${Number(t.progress)}/${Number(t.goal)} · ${ic('coins')}${Number(t.coins)}</div></div>
        ${t.claimed ? `<span class="task-done">${ic('check')} Done</span>`
          : t.done ? `<button type="button" class="store-btn buy" data-claim-task="${escapeAttr(t.key)}">Claim</button>`
          : `<button type="button" class="store-btn ghost" data-task-go="${escapeAttr(t.go)}">Go</button>`}
      </div>`).join('')}`;
  }catch(e){ body.innerHTML = emptyStateHTML('⚠️', 'Could not load tasks', escapeHTML(e.message || '')); }
}
function taskGo(where){
  closeOverlay('screen-tasks');
  closeOverlay('screen-user-profile');
  if(where === 'create') openOverlay('screen-create-room');
  else if(where === 'messages') navigateTo('messages');
  else navigateTo('home');
}

/* ---------------------------------------------------------------- edit profile + photo upload */
let pendingAvatar = null;
function openEditProfile(){
  const me = STATE.currentUser || {};
  pendingAvatar = null;
  document.getElementById('edit-avatar-img').src = safeImgUrl(me.avatar);
  document.getElementById('edit-bio').value = me.bio || '';
  document.getElementById('edit-country').value = me.country || '';
  document.getElementById('edit-avatar-input').value = '';
  openModal('edit-profile-modal');
}
// Centre-crop to a square and shrink to 640px JPEG before uploading (fast on mobile data).
function prepareAvatar(file){
  return new Promise((resolve, reject) => {
    if(!/^image\//.test(file.type)) return reject(new Error('Please choose an image file'));
    if(file.size > 15 * 1024 * 1024) return reject(new Error('That image is too large'));
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      const side = Math.min(img.naturalWidth, img.naturalHeight);
      const out = Math.min(640, side);
      const c = document.createElement('canvas');
      c.width = c.height = out;
      c.getContext('2d').drawImage(img, (img.naturalWidth - side) / 2, (img.naturalHeight - side) / 2, side, side, 0, 0, out, out);
      URL.revokeObjectURL(url);
      c.toBlob(b => b ? resolve(b) : reject(new Error('Could not read that image')), 'image/jpeg', 0.88);
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Could not read that image')); };
    img.src = url;
  });
}
async function saveProfile(){
  const btn = document.getElementById('edit-save');
  btn.disabled = true; btn.textContent = 'Saving…';
  try{
    if(pendingAvatar) await Api.uploadAvatar(pendingAvatar);
    await Api.updateMe({ bio: document.getElementById('edit-bio').value.trim().slice(0, 160),
                         country: document.getElementById('edit-country').value.trim().slice(0, 64) });
    await refreshMe();
    closeModal('edit-profile-modal');
    showToast('Profile updated', 'success');
  }catch(e){ showToast(e.message || 'Could not save', 'error'); }
  finally{ btn.disabled = false; btn.textContent = 'Save'; }
}

/* ---------------------------------------------------------------- home banner carousel */
const HOME_BANNERS = [
  { t: 'Daily check-in', s: 'Free coins every day — 7-day streak bonus', a: 'checkin', icon: 'calendar-check', g: 'linear-gradient(120deg,#ff7a45,#ff3ea5)' },
  { t: 'Top gifters this week', s: 'See who is lighting up Vibra', a: 'leaderboard', icon: 'trophy', g: 'linear-gradient(120deg,#7b2ff7,#2fe6d8)' },
  { t: 'Frames & mounts', s: 'Make an entrance they will remember', a: 'store', icon: 'sparkles', g: 'linear-gradient(120deg,#b721ff,#ffc857)' },
  { t: 'Daily tasks', s: 'Chat, gift and host to earn coins', a: 'tasks', icon: 'list-checks', g: 'linear-gradient(120deg,#0ea5e9,#10b981)' },
];
let bannerTimer = null;
function renderHomeBanners(){
  const track = document.getElementById('home-banners');
  if(!track || VIBRA_CONFIG.DEMO_DATA){ if(track) track.parentElement.hidden = true; return; }
  track.innerHTML = HOME_BANNERS.map(b => `
    <button type="button" class="hb" data-banner="${b.a}" style="background:${b.g}">
      <div class="hb-t">${escapeHTML(b.t)}</div><div class="hb-s">${escapeHTML(b.s)}</div>
      <span class="hb-ic">${ic(b.icon)}</span><span class="hb-go">Open ${ic('chevron-right')}</span>
    </button>`).join('');
  document.getElementById('home-banner-dots').innerHTML = HOME_BANNERS.map((_, i) => `<span class="${i ? '' : 'on'}"></span>`).join('');
  clearInterval(bannerTimer);
  bannerTimer = setInterval(() => {
    if(document.hidden) return;
    const w = track.clientWidth;
    if(!w) return;
    const next = (Math.round(track.scrollLeft / w) + 1) % HOME_BANNERS.length;
    track.scrollTo({ left: next * w, behavior: 'smooth' });
  }, 4500);
}
function bannerAction(a){
  if(a === 'checkin') maybeShowCheckin(true);
  else if(a === 'leaderboard') openLeaderboard('rich', 'week');
  else if(a === 'store') openStore('frame');
  else if(a === 'tasks') openTasks();
}

/* ---------------------------------------------------------------- bindings */
function bindPerks(){
  document.getElementById('store-tabs').addEventListener('click', e => {
    const b = e.target.closest('[data-store-tab]'); if(!b) return;
    STATE.storeTab = b.dataset.storeTab; renderStore();
  });
  document.getElementById('store-grid').addEventListener('click', e => {
    const buy = e.target.closest('[data-buy]');
    if(buy){ const it = storeItems.find(i => i.id === Number(buy.dataset.buy)); return storeAction(() => Api.buyItem(Number(buy.dataset.buy)), it ? `${it.name} is yours for ${it.days} days` : 'Bought'); }
    const eq = e.target.closest('[data-equip]');
    if(eq) return storeAction(() => Api.equipItem(Number(eq.dataset.equip)), 'Now in use');
    const un = e.target.closest('[data-unequip]');
    if(un) return storeAction(() => Api.equipItem(null, un.dataset.unequip), 'Taken off');
    const ap = e.target.closest('[data-apply-theme]');
    if(ap){
      if(!(STATE.activeRoom && STATE.isHost && typeof STATE.activeRoom.id === 'number')){ showToast('Open a room you host, then pick this theme in Room settings', 'info'); return; }
      return Api.updateRoomSettings(STATE.activeRoom.id, { theme: ap.dataset.applyTheme })
        .then(s => { applyRoomSettings(s, false); closeOverlay('screen-store'); showToast('Theme applied to your room', 'success'); })
        .catch(err => showToast(err.message || 'Could not apply theme', 'error'));
    }
    const pv = e.target.closest('[data-preview-mount]');
    if(pv){ const me = STATE.currentUser || {}; FX.mountEntry({ mount: pv.dataset.previewMount, name: me.name || 'You', avatar: me.avatar, vip: me.vip, preview: true }); }
  });
  document.getElementById('lb-boards').addEventListener('click', e => { const b = e.target.closest('[data-lb-board]'); if(b) openLeaderboard(b.dataset.lbBoard); });
  document.getElementById('lb-periods').addEventListener('click', e => { const b = e.target.closest('[data-lb-period]'); if(b) openLeaderboard(null, b.dataset.lbPeriod); });
  document.getElementById('lb-body').addEventListener('click', e => {
    const r = e.target.closest('[data-lb-room]'); if(!r) return;
    closeOverlay('screen-leaderboard'); openRoom(Number(r.dataset.lbRoom));
  });
  document.getElementById('checkin-body').addEventListener('click', e => { if(e.target.closest('#checkin-claim')) claimCheckin(); });
  document.getElementById('tasks-body').addEventListener('click', async e => {
    if(e.target.closest('#tasks-open-checkin')) return maybeShowCheckin(true);
    const c = e.target.closest('[data-claim-task]');
    if(c){
      c.disabled = true;
      try{ const res = await Api.claimTask(c.dataset.claimTask); STATE.walletBalance = res.balance; updateWalletUI(); FX.burstAt(c, 40); showToast(`+${res.coins} coins`, 'success'); openTasks(); }
      catch(err){ showToast(err.message || 'Could not claim', 'error'); c.disabled = false; }
      return;
    }
    const go = e.target.closest('[data-task-go]');
    if(go) taskGo(go.dataset.taskGo);
  });
  document.getElementById('edit-avatar-btn').addEventListener('click', () => document.getElementById('edit-avatar-input').click());
  document.getElementById('edit-avatar-input').addEventListener('change', async e => {
    const f = e.target.files && e.target.files[0]; if(!f) return;
    try{ pendingAvatar = await prepareAvatar(f); document.getElementById('edit-avatar-img').src = URL.createObjectURL(pendingAvatar); }
    catch(err){ showToast(err.message, 'error'); }
  });
  document.getElementById('edit-save').addEventListener('click', saveProfile);
  document.getElementById('home-banners').addEventListener('click', e => { const b = e.target.closest('[data-banner]'); if(b) bannerAction(b.dataset.banner); });
  document.getElementById('home-banners').addEventListener('scroll', e => {
    const t = e.currentTarget, i = Math.round(t.scrollLeft / (t.clientWidth || 1));
    document.querySelectorAll('#home-banner-dots span').forEach((d, n) => d.classList.toggle('on', n === i));
  }, { passive: true });
  document.body.addEventListener('click', e => {
    const m = e.target.closest('[data-me-menu]'); if(!m) return;
    const a = m.dataset.meMenu;
    if(a === 'wallet') openWallet();
    else if(a === 'store') openStore('frame');
    else if(a === 'levels') openLevels();
    else if(a === 'leaderboard') openLeaderboard('rich', 'week');
    else if(a === 'tasks') openTasks();
    else if(a === 'edit') openEditProfile();
    else if(a === 'settings') openOverlay('screen-settings');
  });
}
