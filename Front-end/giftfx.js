/* ============================================================================
   giftfx.js: room animations (all drawn in code, no image assets)
   - flying gifts from the gift button to the recipient's seat
   - gift banners in the chat area and entry banners when someone joins
   - full-screen effects for premium gifts (rocket, fireworks, crown, car, castle, dragon)
   - the global "big gift" banner across the top of the app
   - the Combo button with its countdown ring
   Uses escapeHTML / imgSrc from app.js at call time.
   ============================================================================ */
const FX = (() => {
  const reduced = () => window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const enabled = () => { try { return localStorage.getItem('vibra_fx') !== 'off'; } catch (e) { return true; } };
  const setEnabled = (on) => { try { localStorage.setItem('vibra_fx', on ? 'on' : 'off'); } catch (e) {} };
  const el = (tag, cls, html) => { const n = document.createElement(tag); if (cls) n.className = cls; if (html != null) n.innerHTML = html; return n; };
  const centerOf = (node) => { const r = node.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };

  /* ---------- simple serial queue (banners and full-screen effects play one at a time) ---------- */
  function queue(maxPending) {
    const items = []; let busy = false;
    const next = () => {
      if (busy || !items.length) return;
      busy = true;
      const run = items.shift();
      Promise.resolve().then(run).catch(() => {}).finally(() => { busy = false; next(); });
    };
    return (fn) => { if (items.length >= maxPending) items.shift(); items.push(fn); next(); };
  }
  const bannerQ = queue(6), entryQ = queue(4), fullQ = queue(3), globalQ = queue(4);
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  /* ---------- particles on a full-screen canvas ---------- */
  function particles(canvas) {
    const ctx = canvas.getContext('2d');
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const resize = () => { canvas.width = innerWidth * dpr; canvas.height = innerHeight * dpr; ctx.setTransform(dpr, 0, 0, dpr, 0, 0); };
    resize();
    const list = [];
    let raf = 0, running = true;
    const add = (p) => list.push(Object.assign({ vx: 0, vy: 0, g: 0, life: 1, decay: 0.012, size: 3, color: '#fff', glow: 0, shape: 'dot' }, p));
    const frame = () => {
      if (!running) return;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (let i = list.length - 1; i >= 0; i--) {
        const p = list[i];
        p.vy += p.g; p.x += p.vx; p.y += p.vy; p.life -= p.decay;
        if (p.life <= 0) { list.splice(i, 1); continue; }
        ctx.globalAlpha = Math.max(0, Math.min(1, p.life));
        ctx.shadowBlur = p.glow; ctx.shadowColor = p.color; ctx.fillStyle = p.color;
        if (p.shape === 'star') { star(ctx, p.x, p.y, p.size); }
        else if (p.shape === 'rect') { ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.x / 20); ctx.fillRect(-p.size, -p.size / 2, p.size * 2, p.size); ctx.restore(); }
        else { ctx.beginPath(); ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2); ctx.fill(); }
      }
      ctx.globalAlpha = 1; ctx.shadowBlur = 0;
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return { add, stop: () => { running = false; cancelAnimationFrame(raf); }, list };
  }
  function star(ctx, x, y, r) {
    ctx.beginPath();
    for (let i = 0; i < 10; i++) {
      const a = (Math.PI / 5) * i - Math.PI / 2, rr = i % 2 ? r * 0.45 : r;
      ctx.lineTo(x + Math.cos(a) * rr, y + Math.sin(a) * rr);
    }
    ctx.closePath(); ctx.fill();
  }
  const PALETTE = ['#ff3ea5', '#b721ff', '#ffc857', '#2fe6d8', '#ffffff', '#ff7a45'];
  const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];
  function explode(sys, x, y, n, opts = {}) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2, s = (opts.speed || 5) * (0.4 + Math.random());
      sys.add({ x, y, vx: Math.cos(a) * s, vy: Math.sin(a) * s, g: opts.g ?? 0.06, decay: opts.decay || (0.012 + Math.random() * 0.01),
        size: opts.size || (1.5 + Math.random() * 2.5), color: opts.color || pick(PALETTE), glow: 12, shape: opts.shape || 'dot' });
    }
  }

  /* ---------- flying gift ---------- */
  function flyTo(emoji, fromNode, toNode) {
    if (!enabled() || reduced() || !toNode) return Promise.resolve();
    const from = fromNode ? centerOf(fromNode) : { x: innerWidth / 2, y: innerHeight - 70 };
    const to = centerOf(toNode);
    const n = el('div', 'fx-fly', escapeHTML(emoji));
    document.body.appendChild(n);
    const dx = to.x - from.x, dy = to.y - from.y;
    const anim = n.animate([
      { transform: `translate(${from.x}px, ${from.y}px) translate(-50%,-50%) scale(.4)`, opacity: 0 },
      { transform: `translate(${from.x + dx * 0.35}px, ${from.y + dy * 0.35 - 120}px) translate(-50%,-50%) scale(1.6)`, opacity: 1, offset: 0.45 },
      { transform: `translate(${to.x}px, ${to.y}px) translate(-50%,-50%) scale(.9)`, opacity: 1, offset: 0.9 },
      { transform: `translate(${to.x}px, ${to.y}px) translate(-50%,-50%) scale(1.4)`, opacity: 0 },
    ], { duration: 1100, easing: 'cubic-bezier(.3,.7,.3,1)' });
    return anim.finished.then(() => { n.remove(); burstAt(toNode, 18); });
  }

  /* ---------- sparkle burst at a node (also used for the "burst" gift tier) ---------- */
  function burstAt(node, count = 26) {
    if (!enabled() || reduced() || !node) return;
    const c = centerOf(node);
    const canvas = el('canvas', 'fx-canvas');
    document.body.appendChild(canvas);
    const sys = particles(canvas);
    explode(sys, c.x, c.y, count, { speed: 3.2, g: 0.03, shape: 'star', size: 3 });
    node.classList.add('fx-hit');
    setTimeout(() => node.classList.remove('fx-hit'), 700);
    setTimeout(() => { sys.stop(); canvas.remove(); }, 1600);
  }

  /* ---------- gift banner in the chat area ---------- */
  function giftBanner(g) {
    bannerQ(async () => {
      const layer = document.getElementById('gift-banner-layer');
      if (!layer) return;
      const b = el('div', 'fx-gift-banner', `
        <img class="avatar" src="${imgSrc(g.senderAvatar)}" alt="">
        <div class="t"><b>${escapeHTML(g.senderName)}</b><span>sent ${escapeHTML(g.recipientName)}</span></div>
        <span class="emo">${escapeHTML(g.emoji)}</span>
        <span class="cnt">×${Number(g.count) || 1}</span>`);
      layer.appendChild(b);
      await wait(2600);
      b.classList.add('out');
      await wait(380);
      b.remove();
    });
  }

  /* ---------- entry banner ("X joined") ---------- */
  function entryBanner(u) {
    entryQ(async () => {
      const layer = document.getElementById('entry-banner-layer');
      if (!layer || !enabled()) return;
      const vip = Math.min(5, Number(u.vip) || 0);
      const b = el('div', 'fx-entry' + (u.admin ? ' admin' : vip ? ' vip' : ''), `
        <img class="avatar" src="${imgSrc(u.avatar)}" alt="">
        <span class="lv">${u.admin ? 'ADMIN' : vip ? 'VIP' + vip : 'Lv ' + (Number(u.level) || 1)}</span>
        <span class="t"><b>${escapeHTML(u.name)}</b> joined the room</span>
        <span class="spark"></span>`);
      layer.appendChild(b);
      await wait(reduced() ? 1800 : 2700);
      b.remove();
    });
  }

  /* ---------- mount entrance (store item): vehicle crosses the room ---------- */
  const MOUNT_EMOJI = { bike: '🏍️', car: '🏎️', rocket: '🚀', unicorn: '🦄', ufo: '🛸', dragon: '🐉' };
  const MOUNT_NAME = { bike: 'Street Bike', car: 'Supercar', rocket: 'Rocket', unicorn: 'Unicorn', ufo: 'UFO', dragon: 'Dragon' };
  const mountQ = queue(4);
  function mountEntry(u) {
    if (!MOUNT_EMOJI[u.mount] || (!enabled() && !u.preview)) return;
    mountQ(async () => {
      const lane = el('div', 'fx-mount-lane' + (u.preview ? ' preview' : ''));
      lane.innerHTML = `
        <div class="fx-mount m-${u.mount}"><span class="veh">${MOUNT_EMOJI[u.mount]}</span><span class="trail"></span></div>
        <div class="fx-mount-tag"><img class="avatar" src="${imgSrc(u.avatar)}" alt=""><b>${escapeHTML(u.name)}</b> rode in on ${MOUNT_NAME[u.mount]}</div>`;
      document.body.appendChild(lane);
      let sys = null, canvas = null, t = null;
      if (!reduced()) {
        canvas = el('canvas', 'fx-canvas'); document.body.appendChild(canvas);
        sys = particles(canvas);
        const veh = lane.querySelector('.fx-mount');
        t = setInterval(() => {
          const c = centerOf(veh);
          sys.add({ x: c.x - 34, y: c.y + 14 + (Math.random() - .5) * 18, vx: -3 - Math.random() * 3, vy: (Math.random() - .5),
            decay: .03, size: 2 + Math.random() * 3, color: pick(['#ffc857', '#ff3ea5', '#2fe6d8']), glow: 14, shape: Math.random() < .3 ? 'star' : 'dot' });
        }, 24);
      }
      await wait(reduced() ? 2200 : 3400);
      clearInterval(t); lane.remove();
      if (sys) { sys.stop(); canvas.remove(); }
    });
  }

  /* ---------- full-screen premium effects ---------- */
  const KINDS = {
    rocket(stage, sys) {
      const r = el('div', 'fx-big fx-rocket', '🚀'); stage.appendChild(r);
      const flame = setInterval(() => {
        const c = centerOf(r);
        for (let i = 0; i < 6; i++) sys.add({ x: c.x + (Math.random() - .5) * 26, y: c.y + 70, vx: (Math.random() - .5) * 1.5, vy: 3 + Math.random() * 3,
          decay: .03, size: 3 + Math.random() * 4, color: pick(['#ffc857', '#ff7a45', '#ff3ea5']), glow: 18 });
      }, 30);
      for (let i = 0; i < 70; i++) sys.add({ x: Math.random() * innerWidth, y: Math.random() * innerHeight, vy: 6 + Math.random() * 8, decay: .008, size: 1 + Math.random() * 1.5, color: '#fff', glow: 6 });
      return () => clearInterval(flame);
    },
    fireworks(stage, sys) {
      let n = 0;
      const t = setInterval(() => {
        explode(sys, innerWidth * (.15 + Math.random() * .7), innerHeight * (.15 + Math.random() * .4), 70, { speed: 5.5, g: .05, color: pick(PALETTE) });
        if (++n > 9) clearInterval(t);
      }, 260);
      stage.appendChild(el('div', 'fx-big fx-pop', '🎆'));
      return () => clearInterval(t);
    },
    crown(stage, sys) {
      stage.appendChild(el('div', 'fx-rays'));
      stage.appendChild(el('div', 'fx-big fx-descend', '👑'));
      const t = setInterval(() => explode(sys, innerWidth / 2 + (Math.random() - .5) * 160, innerHeight * .42, 6, { speed: 2.5, g: .02, shape: 'star', color: '#ffc857' }), 90);
      return () => clearInterval(t);
    },
    car(stage, sys) {
      stage.appendChild(el('div', 'fx-road'));
      const c = el('div', 'fx-big fx-drive', '🏎️'); stage.appendChild(c);
      const t = setInterval(() => {
        const p = centerOf(c);
        sys.add({ x: p.x - 60, y: p.y + 30 + (Math.random() - .5) * 20, vx: -6 - Math.random() * 6, decay: .03, size: 2 + Math.random() * 2, color: '#2fe6d8', glow: 14 });
      }, 20);
      return () => clearInterval(t);
    },
    castle(stage, sys) {
      stage.appendChild(el('div', 'fx-rays slow'));
      stage.appendChild(el('div', 'fx-big fx-rise', '🏰'));
      const t = setInterval(() => sys.add({ x: Math.random() * innerWidth, y: -10, vx: (Math.random() - .5) * 2, vy: 2 + Math.random() * 2, g: .02, decay: .006,
        size: 4 + Math.random() * 4, color: pick(PALETTE), shape: 'rect' }), 25);
      return () => clearInterval(t);
    },
    dragon(stage, sys) {
      stage.classList.add('fx-shake');
      const d = el('div', 'fx-big fx-dragon', '🐉'); stage.appendChild(d);
      const t = setInterval(() => {
        const p = centerOf(d);
        for (let i = 0; i < 5; i++) sys.add({ x: p.x - 50, y: p.y + 10, vx: -4 - Math.random() * 4, vy: (Math.random() - .5) * 3, decay: .022,
          size: 4 + Math.random() * 6, color: pick(['#ff7a45', '#ffc857', '#ff3ea5']), glow: 22 });
      }, 30);
      return () => clearInterval(t);
    },
  };
  const FULL_MS = { rocket: 3200, fireworks: 3400, crown: 3200, car: 3200, castle: 3600, dragon: 3800 };

  function fullscreen(kind, g) {
    if (!enabled()) return;
    fullQ(async () => {
      const stage = el('div', 'fx-stage');
      const cap = `<b>${escapeHTML(g.senderName)}</b> sent <b>${escapeHTML(g.recipientName)}</b> ${escapeHTML(g.name)}${g.count > 1 ? ' ×' + Number(g.count) : ''}`;
      if (reduced() || !KINDS[kind]) {
        stage.innerHTML = `<div class="fx-big fx-pop">${escapeHTML(g.emoji)}</div><div class="fx-caption">${cap}</div>`;
        document.body.appendChild(stage);
        await wait(2200);
      } else {
        const canvas = el('canvas', 'fx-canvas');
        stage.appendChild(canvas);
        document.body.appendChild(stage);
        const sys = particles(canvas);
        const stop = KINDS[kind](stage, sys) || (() => {});
        stage.appendChild(el('div', 'fx-caption', cap));
        await wait(FULL_MS[kind] || 3000);
        stop();
        stage.classList.add('out');
        await wait(450);
        sys.stop();
      }
      stage.remove();
    });
  }

  /* ---------- global banner across the top of the app ---------- */
  function globalBanner(g, onTap) {
    globalQ(async () => {
      const b = el('button', 'fx-global', `
        <img class="avatar" src="${imgSrc(g.senderAvatar)}" alt="">
        <span class="t"><b>${escapeHTML(g.senderName)}</b> ×${Number(g.count) || 1} ${escapeHTML(g.emoji)} to <b>${escapeHTML(g.recipientName)}</b></span>
        <span class="room">in ${escapeHTML(g.roomName || 'a room')}</span>`);
      b.type = 'button';
      if (onTap) b.addEventListener('click', onTap);
      document.body.appendChild(b);
      await wait(reduced() ? 4000 : 7200);
      b.remove();
    });
  }

  /* ---------- Combo button (countdown ring) ---------- */
  const Combo = (() => {
    let node = null, timer = null, count = 0, onTap = null;
    const SECONDS = 5;
    function ensure() {
      if (node) return node;
      node = el('button', 'fx-combo', `
        <svg viewBox="0 0 44 44" aria-hidden="true"><circle class="trk" cx="22" cy="22" r="20"/><circle class="ring" cx="22" cy="22" r="20"/></svg>
        <span class="lbl">Combo</span><span class="num"></span>`);
      node.type = 'button';
      node.setAttribute('aria-label', 'Send the same gift again');
      node.addEventListener('click', () => { if (onTap) onTap(); });
      document.getElementById('screen-room').appendChild(node);
      return node;
    }
    function restart() {
      const ring = node.querySelector('.ring');
      ring.style.animation = 'none'; void ring.getBoundingClientRect(); ring.style.animation = '';
      clearTimeout(timer);
      timer = setTimeout(hide, SECONDS * 1000);
    }
    function show(handler, startCount) {
      ensure(); onTap = handler; count = startCount || 1;
      node.querySelector('.num').textContent = '×' + count;
      node.classList.add('show');
      restart();
    }
    function bump(n) {
      if (!node) return;
      count = n;
      const num = node.querySelector('.num');
      num.textContent = '×' + count;
      num.classList.remove('bump'); void num.offsetWidth; num.classList.add('bump');
      restart();
    }
    function hide() { clearTimeout(timer); if (node) node.classList.remove('show'); onTap = null; }
    return { show, bump, hide, get count() { return count; } };
  })();

  return { enabled, setEnabled, flyTo, burstAt, giftBanner, entryBanner, mountEntry, fullscreen, globalBanner, Combo };
})();

// 58200000 -> "58.2M"
function formatScore(n) {
  n = Number(n) || 0;
  if (n >= 1e9) return (n / 1e9).toFixed(n >= 1e10 ? 0 : 1).replace(/\.0$/, '') + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(/\.0$/, '') + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(/\.0$/, '') + 'K';
  return String(n);
}
