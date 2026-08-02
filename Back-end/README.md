# Vibra Backend (Django + DRF + Channels)

This replaces the localStorage-only state in the current front-end prototype
with a real API, real-time sync, a real wallet ledger, and a hook for actual
voice (LiveKit). It's a scaffold — models, endpoints, and real-time wiring
are all in place and verified to boot cleanly, but it needs your DB/Redis/
Razorpay/LiveKit credentials to actually run end-to-end.

## What maps to what in the current frontend

| Prototype (app.js) | Replaced by |
|---|---|
| `STATE.accounts` in localStorage | `apps/accounts` — real signup/login, JWT |
| `setWallet()` | `apps/wallet` — ledger of `Transaction` rows, balance is always summed, never stored as one editable number |
| Fake seat/speaking simulation | `apps/rooms` REST endpoints + `RoomConsumer` (Channels) broadcasting real seat/message/gift/presence events over WebSocket |
| No real audio | `apps/rooms/voice.py` mints a scoped LiveKit token per user per room; the LiveKit JS SDK on the frontend handles actual audio capture/playback |
| Mock gift sending | `wallet/services.send_gift()` — atomic, row-locked, can't be double-spent |

## Project layout

```
config/            settings, urls, asgi (HTTP + WebSocket), routing, JWT ws auth
apps/accounts/      signup, guest login, profile
apps/rooms/         rooms, seats, messages, hand-raise, Channels consumer, voice tokens
apps/wallet/        coin ledger, Razorpay order + webhook, gift sending
apps/notifications/ notification model (extend with follow/gift/mention triggers)
```

## Running locally

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in DB creds; Razorpay/LiveKit keys can stay blank to boot

# needs Postgres + Redis running locally (or point DB_HOST/REDIS_URL at Docker containers)
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser

# HTTP + WebSocket together, since ASGI_APPLICATION is set:
daphne -b 0.0.0.0 -p 8000 config.asgi:application
```

Connect a WebSocket client to `ws://localhost:8000/ws/rooms/<id>/?token=<jwt access token>`.

## Deploying on Render

- One **Web Service** running `daphne config.asgi:application` (not `gunicorn` — you need ASGI for the WebSocket to work)
- One **Redis** instance (Render add-on or external) for the Channels layer
- One **PostgreSQL** instance (Render Postgres)
- Env vars from `.env.example` set in the Render dashboard
- Razorpay webhook URL pointed at `https://<your-render-domain>/api/wallet/webhook/razorpay/`

## What's intentionally NOT done yet (next steps)

- Host moderation endpoints (force-mute, kick, ban) — `Seat`/`Room` models have the fields to support this, no views yet
- Push notifications (would hang off `apps/notifications`)
- Rate limiting is a blanket `300/min` per user — tighten per-endpoint (e.g. messages should be much lower)
- Admin-side content moderation / profanity filtering on `Message.text`
- `livekit-api` was pinned at `0.7.1` in requirements.txt but the latest
  available (1.2.0 at time of writing) was used to verify the token code —
  double check `AccessToken`/`VideoGrants` method signatures against
  whichever version you actually install.
