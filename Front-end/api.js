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

// Auto-detect API base: use relative URL on production, localhost in dev.
// This way the same code works both locally and on vibra.sahilmuhd.com.
const API_BASE = (
  window.location.hostname === 'localhost' ||
  window.location.hostname === '127.0.0.1' ||
  window.location.protocol === 'file:'
) ? 'http://localhost:8000/api' : '/api';


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

  // ---- low-level request helper: adds the auth header, retries once
  // after a token refresh if the access token expired (401) ----
  async request(path, { method = "GET", body, auth = true, retry = true } = {}) {
    const headers = { "Content-Type": "application/json" };
    if (auth) {
      const token = this.getAccessToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (res.status === 401 && auth && retry) {
      const refreshed = await this.refreshAccessToken();
      if (refreshed) return this.request(path, { method, body, auth, retry: false });
    }

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const message = data.detail || Object.values(data)[0] || "Request failed";
      throw new Error(Array.isArray(message) ? message[0] : message);
    }
    return data;
  },

  async refreshAccessToken() {
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
      this.setTokens(data.access, null);
      return true;
    } catch {
      return false;
    }
  },

  // ---- auth ----
  async signup({ name, username, email, password, dob }) {
    const data = await this.request("/auth/signup/", {
      method: "POST",
      auth: false,
      body: { name, username, email, password, dob },
    });
    this.setTokens(data.access, data.refresh);
    return data.user;
  },

  async login({ username, password }) {
    // Uses SimpleJWT's default TokenObtainPairView, which expects the
    // USERNAME_FIELD (username) + password.
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
  async listRooms() {
    return this.request("/rooms/");
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

  async takeSeat(roomId, position) {
    return this.request(`/rooms/${roomId}/seats/${position}/take/`, { method: "POST" });
  },

  async leaveSeat(roomId, position) {
    return this.request(`/rooms/${roomId}/seats/${position}/leave/`, { method: "POST" });
  },

  async toggleMute(roomId, position) {
    return this.request(`/rooms/${roomId}/seats/${position}/mute/`, { method: "POST" });
  },

  async raiseHand(roomId) {
    return this.request(`/rooms/${roomId}/hand-raise/`, { method: "POST" });
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
  // Call this after taking a seat / entering a room. Returns the raw
  // WebSocket so app.js can attach its own onmessage handler.
  connectRoomSocket(roomId, onEvent) {
    const token = this.getAccessToken();
    const wsBase = API_BASE.replace(/^http/, "ws").replace("/api", "");
    const socket = new WebSocket(`${wsBase}/ws/rooms/${roomId}/?token=${token}`);
    socket.onmessage = (msg) => {
      try { onEvent(JSON.parse(msg.data)); } catch (e) { console.error("bad ws message", e); }
    };
    return socket;
  },
};

/* ==========================================================================
   INTEGRATION NOTES — what to change in app.js

   1. doLogin(identifier) — replace the localStorage lookup with:
        async function doLogin(identifier, password) {
          try {
            const user = await Api.login({ username: identifier, password });
            loginAs(user); // keep your existing loginAs() for UI state
          } catch (e) { showToast(e.message, 'error'); }
        }
      Note: your current login screen only collects one field ("identifier")
      used as either email or username with no real password check — you'll
      need to make sure the password field's value is actually passed in.

   2. doSignup(data) — replace the localStorage push with:
        async function doSignup(data) {
          try {
            const user = await Api.signup({
              name: data.name, username: data.username,
              email: data.email, password: data.password, dob: data.dob,
            });
            switchAuthScreen('screen-login', 'screen-signup');
            // ... rest of your existing success UI
          } catch (e) { showToast(e.message, 'error'); }
        }

   3. Room list (wherever DATA.rooms / STATE.rooms is read for rendering) —
      replace the static array with:
        const rooms = await Api.listRooms();
      and adapt roomCardHTML() field names (Api returns online_count,
      thumbnail_seed — match or rename to what your template expects).

   4. createRoom(name, desc, category) — replace the local array push with:
        async function createRoom(name, desc, category) {
          const room = await Api.createRoom({ name, category, description: desc });
          closeOverlay('screen-create-room');
          openRoom(room.id); // fetch full detail + seats via Api.getRoom()
        }

   5. Taking a seat (wherever the UI currently just mutates STATE.activeRoom
      seats locally) — call Api.takeSeat(roomId, position) instead, then
      re-render from the WebSocket broadcast rather than local mutation.

   6. Chat send — replace the local message push with Api.sendMessage(),
      and render incoming messages from the WebSocket's `message_new` event
      instead of from a local array, so multiple users actually see each
      other's messages.

   7. On entering a room, call:
        const socket = Api.connectRoomSocket(room.id, (event) => {
          switch (event.event) {
            case 'seat_update': // re-render that seat
              break;
            case 'message_new': // append to chat
              break;
            case 'gift_sent': // play gift animation
              break;
            case 'presence_update': // update online count
              break;
          }
        });
      Close it (socket.close()) when leaving the room.

   Do this incrementally — wire auth first, confirm signup/login work end
   to end in the browser, THEN move to rooms, THEN messages/seats/gifts.
   Trying to swap everything at once makes it much harder to tell which
   change broke something.
   ========================================================================== */
