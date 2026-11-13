#!/usr/bin/env bash
# Update Vibra on the VPS to the latest code of its branch.
#
#   sudo bash /srv/vibra/deploy/deploy.sh
#
set -euo pipefail
APP_DIR=/srv/vibra
[ "$(id -u)" -eq 0 ] || { echo "Run as root: sudo bash deploy.sh" >&2; exit 1; }

cd "$APP_DIR"
BRANCH="$(sudo -u vibra git rev-parse --abbrev-ref HEAD)"
echo "==> Pulling $BRANCH"
sudo -u vibra git pull --ff-only

echo "==> Dependencies, migrations, static files"
sudo -u vibra "$APP_DIR/venv/bin/pip" install -q -r Back-end/requirements.txt
cd Back-end
sudo -u vibra "$APP_DIR/venv/bin/python" manage.py migrate --noinput
sudo -u vibra "$APP_DIR/venv/bin/python" manage.py collectstatic --noinput -v 0

echo "==> Restarting"
install -m 644 "$APP_DIR"/deploy/systemd/vibra-*.service "$APP_DIR"/deploy/systemd/vibra-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl restart vibra-api
sleep 2
systemctl is-active --quiet vibra-api && echo "vibra-api is running ($(sudo -u vibra git -C "$APP_DIR" log -1 --format='%h %s'))" \
  || { echo "vibra-api failed to start:"; journalctl -u vibra-api -n 30 --no-pager; exit 1; }
