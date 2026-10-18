/* ==========================================================================
   Vibra API client — wraps the Django backend you already have running.
   Drop this file in as api.js and include it BEFORE app.js in index.html:
     <script src="api.js"></script>
     <script src="app.js"></script>

   Everything here mirrors the endpoints you already tested with curl:
   signup, login, rooms, seats, messages. Swap the calls in app.js that
   currently touch Storage/localStorage for these instead — see the
   integration notes at the bottom of this file for exactly which
   functions to change.
   ========================================================================== */

// ---- configuration -------------------------------------------------------
// Defaults keep the previous behaviour (localhost in dev, the Render API in
// production). To override WITHOUT editing this file, define
//   <script>window.__VIBRA_CONFIG__ = { API_BASE: 'https://api.example.com/api' }</script>
// before api.js. DEMO_DATA=true re-enables the old mock rooms/users/wallet so
// the UI can still be demoed offline; it must stay false for real use.
const VIBRA_CONFIG = Object.assign({
  API_BASE: (
    window.location.hostname === 'localhost' ||
    window.location.hostname === '127.0.0.1' ||
    window.location.protocol === 'file:'
  ) ? 'http://localhost:8000/api' : 'https://vibra-backend-vac1.onrender.com/api',
  DEMO_DATA: false,
}, window.__VIBRA_CONFIG__ || {});
const API_BASE = VIBRA_CONFIG.API_BASE;


const Api = {
  // ---- token storage (separate from your existing Storage.KEYS, so it
  // doesn't collide with the old localStorage-only account data) ----
  getAccessToken() { return localStorage.getItem("vibra_access"); },
  getRefreshToken() { return localStorage.getItem("vibra_refresh"); },
  setTokens(access, refresh) {
    localStorage.setItem("vibra_access", access);
    if (refresh) localStorage.setItem("vibra_refresh", refresh);
  },
  clearTokens() {
    localStorage.removeItem("vibra_access");
    localStorage.removeItem("vibra_refresh");
  },

  // Set by app.js: called once when the session can no longer be refreshed.
  onAuthLost: null,
  _refreshing: null,

  // ---- low-level request helper: adds the auth header, retries once
  // after a token refresh if the access token expired (401) ----
  async request(path, { method = "GET", body, auth = true, retry = true, keepalive = false } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (auth) {
      const token = this.getAccessToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }

    let res;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        method,
        headers,
        keepalive,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      const err = new Error("Can't reach the Vibra server. Check your connection.");
      err.status = 0;
      throw err;
    }

    if (res.status === 401 && auth && retry) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) return this.request(path, { method, body, auth, retry: false, keepalive });
      // Refresh token missing/expired/revoked: the session is over.
      const hadSession = !!this.getAccessToken();
      this.clearTokens();
      if (hadSession && typeof this.onAuthLost === "function") this.onAuthLost();
    }

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const first = data && typeof data === "object" ? Object.values(data)[0] : null;
      const message = (data && data.detail) || first || "Request failed";
      const err = new Error(Array.isArray(message) ? String(message[0]) : String(message));
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  },

  // Single-flight: several requests failing with 401 at once share ONE refresh
  // call instead of racing each other.
  refreshAccessToken() {
    if (this._refreshing) return this._refreshing;
    this._refreshing = (async () => {
      const refresh = this.getRefreshToken();
      if (!refresh) return false;
      try {
        const res = await fetch(`${API_BASE}/auth/login/refresh/`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh }),
        });
        if (!res.ok) return false;
        const data = await res.json();
        this.setTokens(data.access, data.refresh || null);
        return true;
      } catch {
        return false;
      }
    })().finally(() => { this._refreshing = null; });
    return this._refreshing;
  },

  hasSession() { return !!(this.getAccessToken() || this.getRefreshToken()); },

  // ---- auth ----
  async signup({ name, username, email, password, dob }) {
    // The UI sends new users to the login screen after signup, so tokens are
    // deliberately NOT stored here: otherwise a reload would silently log the
    // user in even though they never saw a logged-in state.
    const data = await this.request("/auth/signup/", {
      method: "POST",
      auth: false,
      body: { name, username, email, password, dob },
    });
    return data.user;
  },

  async login({ username, password }) {
    // `username` may be a username or an email address (case-insensitive).
    const data = await this.request("/auth/login/", {
      method: "POST",
      auth: false,
      body: { username, password },
    });
    this.setTokens(data.access, data.refresh);
    return this.me();
  },

  async guestLogin() {
    const data = await this.request("/auth/guest/", { method: "POST", auth: false });
    this.setTokens(data.access, data.refresh);
    return data.user;
  },

  async me() {
    return this.request("/auth/me/");
  },

  logout() {
    this.clearTokens();
  },

  // ---- rooms ----
  async listRooms(category) {
    const q = category && category !== "All" ? `?category=${encodeURIComponent(category.toLowerCase())}` : "";
    return this.request(`/rooms/${q}`);
  },

  async createRoom({ name, category, description }) {
    return this.request("/rooms/", {
      method: "POST",
      body: { name, category, description },
    });
  },

  async getRoom(roomId) {
    return this.request(`/rooms/${roomId}/`);
  },

  // Registers the caller as "in the room" and returns the full room snapshot.
  async joinRoom(roomId) {
    return this.request(`/rooms/${roomId}/join/`, { method: "POST" });
  },

  // Frees the caller's seat/hand-raise and removes them from the room.
  async leaveRoom(roomId) {
    return this.request(`/rooms/${roomId}/leave/`, { method: "POST" });
  },

  // Best-effort leave for page unload (keepalive lets it outlive the page).
  // No refresh/retry: if the token is stale the server-side cleanup in Phase 2
  // (disconnect handling) is the safety net.
  leaveRoomOnExit(roomId) {
    try { return this.request(`/rooms/${roomId}/leave/`, { method: "POST", retry: false, keepalive: true }).catch(() => {}); }
    catch { return Promise.resolve(); }
  },

  async takeSeat(roomId, position) {
    return this.request(`/rooms/${roomId}/seats/${position}/take/`, { method: "POST" });
  },

  async leaveSeat(roomId, position) {
    return this.request(`/rooms/${roomId}/seats/${position}/leave/`, { method: "POST" });
  },

  async toggleMute(roomId, position) {
    return this.request(`/rooms/${roomId}/seats/${position}/mute/`, { method: "POST" });
  },

  async forceMute(roomId, position) {
    return this.request(`/rooms/${roomId}/seats/${position}/force-mute/`, { method: "POST" });
  },

  async lockSeat(roomId, position) {
    return this.request(`/rooms/${roomId}/seats/${position}/lock/`, { method: "POST" });
  },

  async kickParticipant(roomId, userId) {
    return this.request(`/rooms/${roomId}/kick/`, { method: "POST", body: { user_id: userId } });
  },

  async endRoom(roomId) {
    return this.request(`/rooms/${roomId}/end/`, { method: "POST" });
  },

  async raiseHand(roomId) {
    return this.request(`/rooms/${roomId}/hand-raise/`, { method: "POST" });
  },

  async lowerHand(roomId) {
    return this.request(`/rooms/${roomId}/hand-raise/`, { method: "DELETE" });
  },

  // ---- voice (LiveKit) ----
  // Call right after taking a seat (or on entering a room to listen).
  // Returns { token, url, room } — hand the token+url straight to the
  // LiveKit JS SDK, which does the actual audio work.
  async getVoiceToken(roomId) {
    return this.request(`/rooms/${roomId}/voice-token/`, { method: "POST" });
  },

  // ---- messages ----
  async listMessages(roomId) {
    return this.request(`/rooms/${roomId}/messages/`);
  },

  async sendMessage(roomId, text, replyTo = null) {
    return this.request(`/rooms/${roomId}/messages/`, {
      method: "POST",
      body: { text, reply_to: replyTo },
    });
  },

  // ---- wallet ----
  async getBalance() {
    return this.request("/wallet/balance/");
  },

  async listTransactions() {
    return this.request("/wallet/transactions/");
  },

  async listGifts() {
    return this.request("/wallet/gifts/");
  },

  async sendGift(roomId, recipientId, giftId, combo = 1) {
    return this.request("/wallet/gifts/send/", {
      method: "POST",
      body: { room_id: roomId, recipient_id: recipientId, gift_id: giftId, combo },
    });
  },

  // ---- real-time (WebSocket) ----
  // Call this after joining a room. Returns the raw WebSocket so app.js can
  // attach its own handlers. The JWT travels in the query string because
  // browsers cannot set headers on a WebSocket handshake.
  wsUrl(roomId) {
    const token = this.getAccessToken() || "";
    const wsBase = API_BASE.replace(/^http/, "ws").replace(/\/api\/?$/, "");
    return `${wsBase}/ws/rooms/${roomId}/?token=${encodeURIComponent(token)}`;
  },
  connectRoomSocket(roomId, onEvent, { onClose, onOpen } = {}) {
    const socket = new WebSocket(this.wsUrl(roomId));
    socket.onmessage = (msg) => {
      try { onEvent(JSON.parse(msg.data)); } catch (e) { console.error("bad ws message", e); }
    };
    if (onOpen) socket.onopen = onOpen;
    if (onClose) socket.onclose = onClose;
    return socket;
  },

  // ---- Password reset ----
  async requestPasswordReset(email) {
    return this.request("/auth/password-reset/", { method: "POST", auth: false, body: { email } });
  },
  async resetPassword(token, newPassword) {
    return this.request("/auth/password-reset/confirm/", {
      method: "POST", auth: false, body: { token, new_password: newPassword },
    });
  },
};

/* ==========================================================================
   Notes
   - Backend contract: see Back-end/README.md. Errors surface as Error objects
     with `.status` (0 = network failure) and `.data` (the parsed JSON body).
   - Tests: `node --test Front-end/tests/` (no dependencies).
   ========================================================================== */
