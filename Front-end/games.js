/* ============================================================================
   games.js — phase 6: fun in rooms (dice, truth-or-dare wheel, quiz,
   guess the song — no betting: players never stake coins) + seasonal events.
   ============================================================================ */
const DICE_FACES = ['⚀', '⚁', '⚂', '⚃', '⚄', '⚅'];
const WHEEL_COLORS = ['#ff3ea5', '#7b2ff7', '#2fe6d8', '#ffc857', '#ff7a45', '#10b981', '#0ea5e9', '#e11d48', '#a855f7', '#f59e0b', '#14b8a6', '#ec4899'];

function roomIdOrNull(){ return STATE.activeRoom && typeof STATE.activeRoom.id === 'number' ? STATE.activeRoom.id : null; }

/* ---------------------------------------------------------------- games sheet */
function openGamesSheet(){
  const mod = canModerate();
  document.querySelectorAll('#games-grid [data-game]').forEach(b => {
    const hostOnly = b.dataset.game !== 'dice';
    b.classList.toggle('locked', hostOnly && !mod);
  });
  document.getElementById('games-hint').hidden = mod;
  document.getElementById('wheel-modes').hidden = true;
  openModal('games-modal');
}
async function gameRequest(action, body){
  const rid = roomIdOrNull();
  if(!rid){ showToast('Games work in live rooms', 'info'); return null; }
  try{ return await Api.gameAction(rid, action, body); }
  catch(e){ showToast(e.message || 'Could not do that', 'error'); return null; }
}

/* ---------------------------------------------------------------- dice */
function showDice(ev){
  const layer = document.getElementById('game-fx');
  const d = document.createElement('div');
  d.className = 'dice-pop';
  d.innerHTML = `<div class="dice-cube">${DICE_FACES[0]}</div><div class="dice-who">${escapeHTML(ev.user.username)}</div>`;
  layer.appendChild(d);
  const cube = d.querySelector('.dice-cube');
  let n = 0;
  const spin = setInterval(() => { cube.textContent = DICE_FACES[Math.floor(Math.random() * 6)]; if(++n > 9){ clearInterval(spin); cube.textContent = DICE_FACES[ev.value - 1]; d.classList.add('landed'); } }, 90);
  setTimeout(() => {
    appendChatMessage({ notice: true, name: ev.user.username, text: `rolled the dice 🎲 ${ev.value}` });
  }, 950);
  setTimeout(() => d.remove(), 3200);
}

/* ---------------------------------------------------------------- truth-or-dare wheel */
function showWheel(ev){
  const ov = document.getElementById('wheel-overlay');
  const n = ev.candidates.length;
  const seg = 360 / n;
  const grad = ev.candidates.map((_, i) => `${WHEEL_COLORS[i % WHEEL_COLORS.length]} ${i * seg}deg ${(i + 1) * seg}deg`).join(', ');
  const labels = ev.candidates.map((u, i) => `<span class="wl" style="transform:rotate(${i * seg + seg / 2}deg)"><b>${escapeHTML(u.username.slice(0, 10))}</b></span>`).join('');
  const idx = Math.max(0, ev.candidates.findIndex(u => u.id === ev.target.id));
  // pointer sits at the top: land the middle of the target segment there, after 5 full turns
  const turn = 360 * 5 + (360 - (idx * seg + seg / 2));
  ov.innerHTML = `<div class="wheel-box">
      <div class="wheel-title">${ev.kind === 'truth' ? 'Truth' : 'Dare'} wheel · spun by ${escapeHTML(ev.by.username)}</div>
      <div class="wheel-wrap"><div class="wheel-pointer"></div><div class="wheel" style="background:conic-gradient(${grad})">${labels}</div><div class="wheel-hub">${ev.kind === 'truth' ? '🤔' : '🔥'}</div></div>
      <div class="wheel-result" hidden></div>
      <button type="button" class="btn btn-glass btn-sm wheel-close" data-wheel-close>Close</button></div>`;
  ov.hidden = false;
  const wheel = ov.querySelector('.wheel');
  requestAnimationFrame(() => requestAnimationFrame(() => { wheel.style.transform = `rotate(${turn}deg)`; }));
  setTimeout(() => {
    const r = ov.querySelector('.wheel-result');
    r.hidden = false;
    r.innerHTML = `<span class="wr-kind k-${escapeAttr(ev.kind)}">${ev.kind === 'truth' ? 'TRUTH' : 'DARE'}</span>
      <div class="wr-who"><img class="avatar" src="${imgSrc(ev.target.avatar_url)}" alt=""> ${escapeHTML(ev.target.username)}</div>
      <div class="wr-prompt">${escapeHTML(ev.prompt)}</div>`;
    appendChatMessage({ system: true, text: `🎡 ${ev.kind === 'truth' ? 'Truth' : 'Dare'} for ${ev.target.username}: ${ev.prompt}` });
  }, 3400);
  clearTimeout(STATE.wheelHide);
  STATE.wheelHide = setTimeout(() => { ov.hidden = true; }, 11000);
}

/* ---------------------------------------------------------------- quiz / guess the song */
let currentGame = null;
function openQuizSetup(kind){
  STATE.quizKind = kind;
  document.querySelectorAll('#quiz-kind [data-quiz-kind]').forEach(b => b.classList.toggle('active', b.dataset.quizKind === kind));
  document.getElementById('quiz-options-wrap').hidden = kind !== 'quiz';
  document.getElementById('quiz-answer-wrap').hidden = kind !== 'guess';
  document.getElementById('quiz-question').placeholder = kind === 'quiz' ? 'e.g. Which planet is the hottest?' : 'Hint (optional) — e.g. A 2010s Bollywood hit';
  document.getElementById('quiz-guess-tip').hidden = kind !== 'guess';
  document.querySelectorAll('#quiz-seconds .chip').forEach(c => c.classList.toggle('active', Number(c.dataset.secs) === (kind === 'quiz' ? 20 : 60)));
  openModal('quiz-modal');
}
async function startQuiz(){
  const kind = STATE.quizKind || 'quiz';
  const secs = Number((document.querySelector('#quiz-seconds .chip.active') || {}).dataset?.secs || 30);
  const body = { kind, question: document.getElementById('quiz-question').value.trim(),
                 prize: Number(document.getElementById('quiz-prize').value || 0), seconds: secs };
  if(kind === 'quiz'){
    const opts = [...document.querySelectorAll('#quiz-options input[type=text]')].map(i => i.value.trim());
    const correctIdx = [...document.querySelectorAll('#quiz-options input[type=radio]')].findIndex(r => r.checked);
    const filled = opts.map((t, i) => ({ t, i })).filter(o => o.t);
    body.options = filled.map(o => o.t);
    body.correct = filled.findIndex(o => o.i === correctIdx);
  } else {
    body.answer = document.getElementById('quiz-answer').value.trim();
  }
  const btn = document.getElementById('quiz-start');
  btn.disabled = true;
  const res = await gameRequest('start', body);
  btn.disabled = false;
  if(!res) return;
  if(res.balance != null){ STATE.walletBalance = res.balance; updateWalletUI(); }
  closeModal('quiz-modal');
  ['quiz-question', 'quiz-answer'].forEach(id => { document.getElementById(id).value = ''; });
  document.querySelectorAll('#quiz-options input[type=text]').forEach(i => { i.value = ''; });
}
function showGameCard(g){
  currentGame = Object.assign({ answered: false, tries: 0 }, g);
  const card = document.getElementById('game-card');
  const mine = STATE.currentUser && g.created_by && g.created_by.id === STATE.currentUser.id;
  const answered = g.my_answer != null || (g.kind === 'guess' && g.my_answers >= 3);
  card.hidden = false;
  card.className = `game-card k-${g.kind}`;
  card.innerHTML = `
    <div class="gc-head"><span class="gc-kind">${g.kind === 'quiz' ? `${ic('circle-help')} Quiz` : `${ic('music')} Guess the song`}</span>
      ${g.prize ? `<span class="gc-prize">${ic('coins')}${Number(g.prize).toLocaleString()}</span>` : '<span class="gc-prize free">Just for fun</span>'}
      <button type="button" class="gc-min" data-gc-min aria-label="Hide">${ic('chevron-down')}</button></div>
    <div class="gc-q">${escapeHTML(g.question)}</div>
    <div class="gc-timer"><span id="gc-bar"></span></div>
    <div class="gc-body">${mine ? `<div class="gc-wait">You started this — waiting for answers…</div>`
      : g.kind === 'quiz'
        ? `<div class="gc-opts">${g.options.map((o, i) => `<button type="button" class="gc-opt ${String(g.my_answer) === String(i) ? 'picked' : ''}" data-gc-opt="${i}" ${answered ? 'disabled' : ''}>${escapeHTML(o)}</button>`).join('')}</div>
           <div class="gc-note" id="gc-note">${answered ? 'Answer locked 🔒 — results when the timer ends' : 'Pick one — you only get one try'}</div>`
        : `<form class="gc-guess" id="gc-guess"><div class="input-wrap"><input type="text" id="gc-guess-input" maxlength="100" placeholder="Song title" autocomplete="off" ${answered ? 'disabled' : ''}></div>
           <button type="submit" class="btn btn-primary btn-sm" ${answered ? 'disabled' : ''}>Guess</button></form>
           <div class="gc-note" id="gc-note">${answered ? 'No guesses left' : `First right answer wins · ${3 - (g.my_answers || 0)} tries`}</div>`}</div>`;
  tickGameTimer();
}
function tickGameTimer(){
  clearInterval(STATE.gameTimer);
  const g = currentGame;
  if(!g) return;
  const end = new Date(g.ends_at).getTime();
  // full bar = the time that was left when this card first appeared
  const start = end - (g.totalMs || (g.totalMs = Math.max(1000, end - Date.now())));
  const step = () => {
    const left = end - Date.now();
    const bar = document.getElementById('gc-bar');
    if(bar) bar.style.width = `${Math.max(0, Math.min(100, left / (end - start) * 100))}%`;
    if(left <= 0){
      clearInterval(STATE.gameTimer);
      // any client may settle; the server only pays once
      setTimeout(() => { if(currentGame && currentGame.id === g.id && currentGame.status !== 'done') gameRequest('finish', { game_id: g.id }).then(r => { if(r && r.status === 'done') showGameResult(r); }); },
        600 + Math.random() * 900);
    }
  };
  step();
  STATE.gameTimer = setInterval(step, 200);
}
async function answerQuiz(i){
  const g = currentGame; if(!g) return;
  document.querySelectorAll('#game-card .gc-opt').forEach(b => { b.disabled = true; b.classList.toggle('picked', Number(b.dataset.gcOpt) === i); });
  const res = await gameRequest('answer', { game_id: g.id, answer: String(i) });
  const note = document.getElementById('gc-note');
  if(res && note) note.textContent = 'Answer locked 🔒 — results when the timer ends';
  if(!res) document.querySelectorAll('#game-card .gc-opt').forEach(b => { b.disabled = false; b.classList.remove('picked'); });
}
async function answerGuess(text){
  const g = currentGame; if(!g || !text) return;
  const input = document.getElementById('gc-guess-input');
  const res = await gameRequest('answer', { game_id: g.id, answer: text });
  if(!res) return;
  if(res.balance != null){ STATE.walletBalance = res.balance; updateWalletUI(); }
  const note = document.getElementById('gc-note');
  if(!note || !input) return;                 // the result card already replaced this one
  if(res.correct){ note.textContent = '🎉 You got it!'; return; }
  input.value = '';
  document.getElementById('game-card').classList.add('shake');
  setTimeout(() => document.getElementById('game-card').classList.remove('shake'), 500);
  note.textContent = res.left > 0 ? `Not quite — ${res.left} ${res.left === 1 ? 'try' : 'tries'} left` : 'No guesses left';
  if(res.left <= 0){ input.disabled = true; document.querySelector('#gc-guess button').disabled = true; }
}
function showGameResult(r){
  clearInterval(STATE.gameTimer);
  if(currentGame && currentGame.id === r.id) currentGame.status = 'done';
  const card = document.getElementById('game-card');
  const me = STATE.currentUser && STATE.currentUser.id;
  const won = r.winners.some(w => w.id === me);
  card.hidden = false;
  card.className = `game-card done k-${r.kind}`;
  card.innerHTML = `
    <div class="gc-head"><span class="gc-kind">${ic('trophy')} ${r.kind === 'quiz' ? 'Quiz' : 'Guess the song'} — results</span>
      <button type="button" class="gc-min" data-gc-close aria-label="Close">${ic('x')}</button></div>
    <div class="gc-q">${escapeHTML(r.question)}</div>
    <div class="gc-answer">Answer: <b>${escapeHTML(r.answer)}</b></div>
    ${r.winners.length ? `<div class="gc-winners">${r.winners.slice(0, 8).map(w => `<span class="gc-w"><img class="avatar" src="${imgSrc(w.avatar_url)}" alt="">${escapeHTML(w.username)}</span>`).join('')}${r.winners.length > 8 ? `<span class="gc-w more">+${r.winners.length - 8}</span>` : ''}</div>
      ${r.prize_each ? `<div class="gc-each">${ic('coins')} ${Number(r.prize_each).toLocaleString()} coins each</div>` : ''}`
      : '<div class="gc-note">Nobody got it this time.</div>'}`;
  const names = r.winners.map(w => w.username);
  appendChatMessage({ system: true, text: names.length ? `🏆 ${r.kind === 'quiz' ? 'Quiz' : 'Guess the song'}: ${names.slice(0, 5).join(', ')}${names.length > 5 ? ` +${names.length - 5}` : ''} got it — “${r.answer}”` : `⌛ Nobody guessed it — the answer was “${r.answer}”` });
  if(won){
    showToast(r.prize_each ? `You won ${r.prize_each} coins! 🎉` : 'You got it right! 🎉', 'success');
    if(typeof FX !== 'undefined') FX.burstAt(card, 50);
    refreshWallet().then(() => updateWalletUI());
  }
  clearTimeout(STATE.gameCardHide);
  STATE.gameCardHide = setTimeout(() => { if(currentGame && currentGame.id === r.id) hideGameCard(); }, 9000);
}
function hideGameCard(){ clearInterval(STATE.gameTimer); currentGame = null; const c = document.getElementById('game-card'); if(c){ c.hidden = true; c.innerHTML = ''; } }
async function loadCurrentGame(roomId){
  try{
    const g = await Api.currentGame(roomId);
    if(g && g.status === 'open' && new Date(g.ends_at).getTime() > Date.now()) showGameCard(g);
  }catch(e){ /* not in room yet / no games */ }
}
function handleGameEvent(ev){
  if(ev.event === 'game_dice') showDice(ev);
  else if(ev.event === 'game_wheel') showWheel(ev);
  else if(ev.event === 'game_start'){
    showGameCard(ev);
    const by = ev.created_by ? ev.created_by.username : 'The host';
    appendChatMessage({ system: true, text: ev.kind === 'quiz' ? `❓ ${by} started a quiz${ev.prize ? ` for ${ev.prize} coins` : ''}!` : `🎵 ${by} started Guess the song${ev.prize ? ` for ${ev.prize} coins` : ''}!` });
  }
  else if(ev.event === 'game_result') showGameResult(ev);
}

/* ---------------------------------------------------------------- seasonal events */
async function loadEvents(){
  if(VIBRA_CONFIG.DEMO_DATA) return;
  try{ STATE.events = await Api.getEvents(); }catch(e){ STATE.events = []; }
  STATE.liveEvent = (STATE.events || []).find(e => e.live) || null;
  if(typeof renderHomeBanners === 'function') renderHomeBanners();
}
function endsIn(iso){
  const ms = new Date(iso).getTime() - Date.now();
  if(ms <= 0) return 'ended';
  const d = Math.floor(ms / 86400000), h = Math.floor(ms / 3600000) % 24, m = Math.floor(ms / 60000) % 60;
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}
async function openEvent(){
  openOverlay('screen-event');
  const body = document.getElementById('event-body');
  body.innerHTML = emptyStateHTML('⏳', 'Loading…', '');
  await loadEvents();
  const ev = STATE.liveEvent;
  const next = (STATE.events || []).find(e => !e.live);
  if(!ev){
    body.innerHTML = emptyStateHTML('🎉', 'No event right now', next ? `${next.name} starts ${new Date(next.starts_at).toLocaleDateString([], { day: 'numeric', month: 'short' })}.` : 'Check back soon!');
    return;
  }
  let items = [];
  try{ storeItems = await Api.getStore(); items = storeItems.filter(i => ev.item_ids.includes(i.id)); }catch(e){ items = []; }
  const style = ['lights', 'winter'].includes(ev.style) ? ev.style : 'lights';
  const me = STATE.currentUser || {};
  body.innerHTML = `
    <div class="ev-hero ev-${style}">
      <div class="ev-deco" aria-hidden="true"></div>
      <div class="ev-name">${escapeHTML(ev.name)}</div>
      <div class="ev-tag">${escapeHTML(ev.tagline)}</div>
      <div class="ev-ends">${ic('clock')} Ends in <b id="ev-countdown">${escapeHTML(endsIn(ev.ends_at))}</b></div>
    </div>
    <div class="rs-label">Limited edition</div>
    <div class="store-grid ev-items" id="event-items">${items.map(i => {
      const owned = !!i.owned_until;
      const visual = i.kind === 'frame'
        ? `<div class="avatar-wrap sm${frameClass(i.key)}"><img class="avatar" src="${imgSrc(me.avatar)}" alt=""></div>`
        : `<button type="button" class="mount-thumb" data-preview-mount="${escapeAttr(i.key)}" aria-label="Preview">${escapeHTML((MOUNTS[i.key] || {}).emoji || '🎁')}<span>${ic('play')}</span></button>`;
      const action = i.equipped ? `<span class="store-renew">In use</span>`
        : owned ? `<button type="button" class="store-btn" data-equip="${Number(i.id)}">Use</button>`
        : `<button type="button" class="store-btn buy" data-buy="${Number(i.id)}">${ic('coins')} ${Number(i.price).toLocaleString()}</button>`;
      return `<div class="store-card${i.equipped ? ' on' : ''}"><span class="ltd">LIMITED</span>${visual}<div class="nm">${escapeHTML(i.name)}</div><div class="meta">${owned ? escapeHTML(daysLeft(i.owned_until)) : `${Number(i.days)} days`}</div>${action}</div>`;
    }).join('')}</div>
    <div class="rs-label">Event ranking · top gifters</div>
    <div class="lb-list">${ev.ranking.length ? ev.ranking.slice(0, 20).map(r => `
      <div class="lb-row"><span class="lb-rank">${r.rank <= 3 ? ['🥇', '🥈', '🥉'][r.rank - 1] : r.rank}</span>
        <img class="avatar" src="${imgSrc(r.user.avatar_url)}" alt="">
        <div class="lb-meta"><div class="lb-name">${escapeHTML(r.user.username)}</div><div class="lb-bdg">${badgesHTML(r.user)}</div></div>
        <span class="lb-score">${ic('coins')}${escapeHTML(formatScore(r.score))}</span></div>`).join('')
      : emptyStateHTML('🏆', 'No gifts yet this event', 'Send gifts during the event to climb the ranking.')}</div>`;
  clearInterval(STATE.evTimer);
  STATE.evTimer = setInterval(() => { const el = document.getElementById('ev-countdown'); if(!el){ clearInterval(STATE.evTimer); return; } el.textContent = endsIn(ev.ends_at); }, 30000);
}

/* ---------------------------------------------------------------- bindings */
function bindGames(){
  document.getElementById('games-grid').addEventListener('click', e => {
    const b = e.target.closest('[data-game]'); if(!b) return;
    const g = b.dataset.game;
    if(g !== 'dice' && !canModerate()){ showToast('Only the host or a moderator can start this game', 'info'); return; }
    if(g === 'dice'){ closeModal('games-modal'); gameRequest('dice'); }
    else if(g === 'wheel'){ document.getElementById('wheel-modes').hidden = false; }
    else { closeModal('games-modal'); openQuizSetup(g); }
  });
  document.getElementById('wheel-modes').addEventListener('click', e => {
    const b = e.target.closest('[data-wheel-mode]'); if(!b) return;
    closeModal('games-modal');
    gameRequest('wheel', { mode: b.dataset.wheelMode });
  });
  document.getElementById('quiz-kind').addEventListener('click', e => { const b = e.target.closest('[data-quiz-kind]'); if(b) openQuizSetup(b.dataset.quizKind); });
  document.getElementById('quiz-seconds').addEventListener('click', e => {
    const b = e.target.closest('[data-secs]'); if(!b) return;
    document.querySelectorAll('#quiz-seconds .chip').forEach(c => c.classList.toggle('active', c === b));
  });
  document.getElementById('quiz-start').addEventListener('click', startQuiz);
  const card = document.getElementById('game-card');
  card.addEventListener('click', e => {
    const o = e.target.closest('[data-gc-opt]'); if(o) return answerQuiz(Number(o.dataset.gcOpt));
    if(e.target.closest('[data-gc-close]')) return hideGameCard();
    if(e.target.closest('[data-gc-min]')) card.classList.toggle('min');
  });
  card.addEventListener('submit', e => {
    if(e.target.id !== 'gc-guess') return;
    e.preventDefault();
    answerGuess(document.getElementById('gc-guess-input').value.trim());
  });
  document.getElementById('wheel-overlay').addEventListener('click', e => {
    if(e.target.closest('[data-wheel-close]') || e.target.id === 'wheel-overlay') document.getElementById('wheel-overlay').hidden = true;
  });
  document.getElementById('event-body').addEventListener('click', e => {
    const buy = e.target.closest('[data-buy]');
    if(buy) return storeAction(() => Api.buyItem(Number(buy.dataset.buy)), 'Limited item unlocked! ✨').then(openEvent);
    const eq = e.target.closest('[data-equip]');
    if(eq) return storeAction(() => Api.equipItem(Number(eq.dataset.equip)), 'Now in use').then(openEvent);
    const pv = e.target.closest('[data-preview-mount]');
    if(pv){ const me = STATE.currentUser || {}; FX.mountEntry({ mount: pv.dataset.previewMount, name: me.name || 'You', avatar: me.avatar, vip: me.vip, preview: true }); }
  });
}
