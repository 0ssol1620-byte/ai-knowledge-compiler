#!/usr/bin/env bash
set -euo pipefail

case "${PUBLIC_KEY:-}" in
  "ssh-ed25519 "*|"ssh-rsa "*) ;;
  *) echo "PUBLIC_KEY must be an OpenSSH public key" >&2; exit 64 ;;
esac

install -d -m 0700 /root/.ssh
printf '%s\n' "$PUBLIC_KEY" > /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
exec /usr/sbin/sshd -D -e
