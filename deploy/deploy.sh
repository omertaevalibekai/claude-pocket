#!/usr/bin/env bash
# Deploy the Claude Pocket server (status for the iPhone widget) to a small Linux VM.
#
#   SSH_KEY=~/.ssh/my.key ./deploy/deploy.sh opc@1.2.3.4
#
# What it does on the VM (no package manager runs, so a 1 GB box stays responsive):
#   * /opt/claude-pocket/relay.py as a systemd service, user "pocket",
#     listening on 127.0.0.1:8787;
#   * Caddy (static binary from GitHub) in front of it with a free certificate
#     for <ip-with-dashes>.sslip.io, port 443 only;
#   * opens https in firewalld.
# Keys are read from ~/.claude-pocket/keys.json (made by `python pocket.py setup`)
# and sent over SSH stdin, so they never show up in a command line.
#
# The cloud firewall (Oracle: VCN security list) must allow TCP 443 — that part
# is done in the cloud console.
set -euo pipefail

TARGET="${1:?Usage: SSH_KEY=... ./deploy/deploy.sh user@host}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519}"
CADDY_VERSION="${CADDY_VERSION:-2.8.4}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST_IP="${TARGET#*@}"
DOMAIN="${DOMAIN:-${HOST_IP//./-}.sslip.io}"

SSH=(ssh -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=20)
SCP=(scp -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes)

KEYS_FILE="${CLAUDE_POCKET_HOME:-$HOME/.claude-pocket}/keys.json"
[ -f "$KEYS_FILE" ] || { echo "Нет $KEYS_FILE: сначала python pocket.py setup"; exit 1; }
ENV_TEXT="$(python -c "import json,sys; k=json.load(open(sys.argv[1],encoding='utf-8')); print('POCKET_PUSH_KEY='+k['push']); print('POCKET_READ_KEY='+k['read'])" "$KEYS_FILE")"

echo "==> Копирую файлы на $TARGET"
"${SCP[@]}" "$HERE/server/relay.py" "$TARGET:/tmp/claude_pocket_relay.py"

echo "==> Ключи (через stdin)"
printf '%s\n' "$ENV_TEXT" | "${SSH[@]}" "$TARGET" "sudo install -d -m 755 /etc/claude-pocket && sudo tee /etc/claude-pocket/env >/dev/null && sudo chmod 600 /etc/claude-pocket/env"

echo "==> Сервис, Caddy, firewall"
"${SSH[@]}" "$TARGET" "sudo bash -s" <<REMOTE
set -euo pipefail
id pocket >/dev/null 2>&1 || useradd -r -s /sbin/nologin -d /var/lib/claude-pocket pocket
install -d -o pocket -g pocket -m 700 /var/lib/claude-pocket
install -d -m 755 /opt/claude-pocket
install -m 644 /tmp/claude_pocket_relay.py /opt/claude-pocket/relay.py
rm -f /tmp/claude_pocket_relay.py

cat > /etc/systemd/system/claude-pocket.service <<'UNIT'
[Unit]
Description=Claude Pocket (Claude Code status for the phone widget)
After=network.target

[Service]
User=pocket
EnvironmentFile=/etc/claude-pocket/env
Environment=POCKET_STATE=/var/lib/claude-pocket/state.json
ExecStart=/usr/bin/python3 /opt/claude-pocket/relay.py
Restart=always
RestartSec=3
MemoryMax=64M
NoNewPrivileges=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/claude-pocket
ProtectHome=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
UNIT

if [ ! -x /usr/local/bin/caddy ] || ! /usr/local/bin/caddy version | grep -q "v${CADDY_VERSION}"; then
  arch=\$(uname -m); case "\$arch" in x86_64) arch=amd64;; aarch64) arch=arm64;; esac
  curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_\${arch}.tar.gz" -o /tmp/caddy.tgz
  tar -xzf /tmp/caddy.tgz -C /tmp caddy
  install -m 755 /tmp/caddy /usr/local/bin/caddy
  rm -f /tmp/caddy /tmp/caddy.tgz
  command -v restorecon >/dev/null && restorecon /usr/local/bin/caddy || true
fi
id caddy >/dev/null 2>&1 || useradd -r -s /sbin/nologin -d /var/lib/caddy caddy
install -d -o caddy -g caddy -m 700 /var/lib/caddy
install -d -m 755 /etc/caddy
cat > /etc/caddy/Caddyfile <<CADDY
{
	admin off
}

${DOMAIN}:443 {
	encode gzip
	reverse_proxy 127.0.0.1:8787
}
CADDY

cat > /etc/systemd/system/caddy.service <<'UNIT'
[Unit]
Description=Caddy
After=network-online.target
Wants=network-online.target

[Service]
User=caddy
Environment=XDG_DATA_HOME=/var/lib/caddy XDG_CONFIG_HOME=/var/lib/caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
Restart=always
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
MemoryMax=128M
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
UNIT

if command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-service=https >/dev/null
  firewall-cmd --reload >/dev/null
fi

systemctl daemon-reload
systemctl enable --now claude-pocket >/dev/null
systemctl restart claude-pocket
systemctl enable --now caddy >/dev/null
systemctl restart caddy
sleep 2
systemctl is-active claude-pocket caddy
curl -fsS http://127.0.0.1:8787/health && echo " (сервис локально отвечает)"
REMOTE

echo "==> Проверяю снаружи: https://$DOMAIN/health (сертификат выдаётся до минуты)"
for i in $(seq 1 12); do
  if curl -fsS --max-time 8 "https://$DOMAIN/health" >/dev/null 2>&1; then
    echo "Готово: https://$DOMAIN отвечает"
    exit 0
  fi
  sleep 10
done
echo "Снаружи не отвечает. Проверьте, что в облачном файрволе открыт TCP 443."
echo "Журнал Caddy: ssh $TARGET 'sudo journalctl -u caddy -n 40 --no-pager'"
exit 1
