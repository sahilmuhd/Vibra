# Deploying Vibra on the Hostinger VPS (KVM 1)

Everything runs on one VPS, next to the sites already there:

```
vibra.sahilmuhd.com      -> nginx -> /srv/vibra/Front-end   (static website)
api.vibra.sahilmuhd.com  -> nginx -> daphne :8010           (API + WebSockets)
                                     |-- PostgreSQL  (database "vibra", role "vibra")
                                     |-- Redis       (database number 5)
voice audio              -> LiveKit Cloud (not on the VPS)
```

Expected load on KVM 1: about 1 GB RAM and 8 GB disk in total. The API service
is capped at 700 MB of RAM so it can't starve your other sites.

`setup.sh` only **adds** Vibra. It does not edit other nginx sites, databases
or Redis data, it checks `nginx -t` before reloading, and it stops if port 80 is
owned by something other than nginx (for example Apache or a control panel).

---

## 0. Before you start

- The code to deploy must be on `main`. Merge the `backend-hardening` pull request
  first, or deploy that branch directly with `VIBRA_BRANCH=backend-hardening`.
- Have your LiveKit keys ready (LiveKit Cloud > Settings > Keys).
- Find the VPS IP in hPanel > VPS > Overview.

## 1. DNS (do this first; it takes a while to spread)

In the DNS zone for `sahilmuhd.com` (hPanel > Domains > DNS, or wherever the domain lives):

| Type | Name        | Value       |
|------|-------------|-------------|
| A    | `vibra`     | your VPS IP |
| A    | `api.vibra` | your VPS IP |

If `vibra` is currently a CNAME to Render, delete that CNAME and add the A record.

## 2. Install (once)

```bash
ssh root@YOUR_VPS_IP
curl -fsSL https://raw.githubusercontent.com/sahilmuhd/Vibra/main/deploy/setup.sh -o setup.sh
less setup.sh            # read it before running it
sudo bash setup.sh       # or: sudo VIBRA_BRANCH=backend-hardening bash setup.sh
```

At the end it prints `API answers (401 = needs login, as expected)`.

## 3. Add your keys

```bash
sudo nano /srv/vibra/Back-end/.env     # fill LIVEKIT_API_KEY / _SECRET / LIVEKIT_URL
sudo systemctl restart vibra-api
```

The database password and Django secret key were generated for you; don't share
that file.

## 4. HTTPS (once DNS points at the VPS)

```bash
dig +short vibra.sahilmuhd.com api.vibra.sahilmuhd.com    # both should print the VPS IP
sudo certbot --nginx -d vibra.sahilmuhd.com -d api.vibra.sahilmuhd.com
```

Certbot edits only the Vibra config and renews the certificates automatically.

## 5. Check it

- https://api.vibra.sahilmuhd.com/api/rooms/ returns `{"detail": ...}` (401). That's correct.
- https://vibra.sahilmuhd.com: sign in as a guest, create a room, take a seat, talk.
- Admin: create a login with
  `cd /srv/vibra/Back-end && sudo -u vibra ../venv/bin/python manage.py createsuperuser`,
  then go to https://api.vibra.sahilmuhd.com/admin/ (reports, bans, etc.).

## Updating after new commits

```bash
sudo bash /srv/vibra/deploy/deploy.sh
```

This pulls the branch, installs requirements, migrates, collects static files
and restarts the service. The website files update with the pull.

## Day-to-day

| Task | Command |
|------|---------|
| Is it running? | `systemctl status vibra-api` |
| Live logs | `journalctl -u vibra-api -f` |
| Restart | `sudo systemctl restart vibra-api` |
| Cleanup job | `systemctl list-timers vibra-cleanup.timer` |
| Backups | `ls /var/backups/vibra` (nightly, kept 14 days) |
| Restore a backup | `sudo -u postgres pg_restore --clean -d vibra /var/backups/vibra/vibra-YYYY-MM-DD.dump` |

Backups stay on the same VPS. Copy them somewhere else now and then (or enable
Hostinger's VPS snapshots) so a lost server doesn't mean lost data.

## After it works

Once the new site is live, suspend the Render services (Vibra-backend and the
static site) so they stop failing and emailing you.
