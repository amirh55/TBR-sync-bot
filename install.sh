#!/usr/bin/env bash
# TBR Sync Bot — one-command installer for Linux (systemd).
#
#   bash install.sh
#
# Creates a virtualenv, installs dependencies, asks for your tokens, registers a
# systemd service with autostart on boot, and installs the `tbrctl` helper.
set -euo pipefail

SERVICE_NAME="tbr-sync-bot"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/venv"
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"
TBRCTL_PATH="/usr/local/bin/tbrctl"

BOLD=$'\033[1m'; DIM=$'\033[2m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; RESET=$'\033[0m'

say()  { printf '%s\n' "${BOLD}==>${RESET} $*"; }
note() { printf '%s\n' "    ${DIM}$*${RESET}"; }
warn() { printf '%s\n' "${YELLOW}!!  $*${RESET}"; }
die()  { printf '%s\n' "${RED}✘   $*${RESET}" >&2; exit 1; }

if [[ "$(uname -s)" != "Linux" ]]; then
  die "This installer targets Linux with systemd. On another OS, run 'python3 main.py' manually."
fi
command -v systemctl >/dev/null 2>&1 || die "systemctl not found. This installer needs systemd."

if [[ $EUID -eq 0 ]]; then
  SUDO=""
  RUN_USER="${SUDO_USER:-root}"
else
  command -v sudo >/dev/null 2>&1 || die "sudo not found and not running as root."
  SUDO="sudo"
  RUN_USER="$USER"
fi
RUN_GROUP="$(id -gn "$RUN_USER")"

echo
say "TBR Sync Bot installer"
note "project : $PROJECT_DIR"
note "service : $SERVICE_NAME"
note "user    : $RUN_USER"
echo

# ---------------------------------------------------------------- 1. python
say "Checking Python"
PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      PYTHON_BIN="$(command -v "$candidate")"
      break
    fi
  fi
done
[[ -n "$PYTHON_BIN" ]] || die "Python 3.10 or newer is required. Install it with: sudo apt install python3 python3-venv"
note "using $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1))"

if ! "$PYTHON_BIN" -c 'import venv' >/dev/null 2>&1; then
  say "Installing python3-venv"
  $SUDO apt-get update -qq && $SUDO apt-get install -y -qq python3-venv
fi

# ------------------------------------------------------------------ 2. venv
say "Creating virtualenv"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  note "created $VENV_DIR"
else
  note "reusing existing $VENV_DIR"
fi

say "Installing dependencies"
"$VENV_DIR/bin/python" -m pip install --quiet --upgrade pip
"$VENV_DIR/bin/python" -m pip install --quiet -r "$PROJECT_DIR/requirements.txt"
note "$("$VENV_DIR/bin/python" -m pip list --format=freeze 2>/dev/null | tr '\n' ' ' | cut -c1-100)"

# ------------------------------------------------------------------- 3. env
say "Configuration"
if [[ -f "$PROJECT_DIR/.env" ]]; then
  note ".env already exists — keeping it (run 'tbrctl config' to change values)"
else
  "$VENV_DIR/bin/python" "$PROJECT_DIR/setup_env.py"
fi
[[ -f "$PROJECT_DIR/.env" ]] || die "No .env was created; aborting."
chmod 600 "$PROJECT_DIR/.env" 2>/dev/null || true

# --------------------------------------------------------------- 4. systemd
say "Registering systemd service"
$SUDO tee "$UNIT_PATH" >/dev/null <<UNIT
[Unit]
Description=TBR Sync Bot (Bale -> Telegram channel mirror)
Documentation=https://github.com/amirh55/TBR-sync-bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
Group=$RUN_GROUP
WorkingDirectory=$PROJECT_DIR
Environment=PYTHONUNBUFFERED=1
ExecStart=$VENV_DIR/bin/python $PROJECT_DIR/main.py

Restart=always
RestartSec=5
# The bot sits in a long poll; give it room to finish and flush pending albums.
KillSignal=SIGTERM
TimeoutStopSec=60

StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=$PROJECT_DIR

[Install]
WantedBy=multi-user.target
UNIT
note "wrote $UNIT_PATH"

$SUDO systemctl daemon-reload
$SUDO systemctl enable "$SERVICE_NAME" >/dev/null 2>&1
note "autostart on boot: enabled"

# ---------------------------------------------------------------- 5. tbrctl
say "Installing tbrctl"
$SUDO install -m 0755 "$PROJECT_DIR/tbrctl" "$TBRCTL_PATH"
$SUDO sed -i "s|^PROJECT_DIR=.*|PROJECT_DIR=\"$PROJECT_DIR\"|" "$TBRCTL_PATH"
note "installed $TBRCTL_PATH"

# ----------------------------------------------------------------- 6. start
say "Starting the bot"
$SUDO systemctl restart "$SERVICE_NAME"
sleep 3

echo
if $SUDO systemctl is-active --quiet "$SERVICE_NAME"; then
  printf '%s\n' "${GREEN}✔ TBR Sync Bot is running and will start automatically on boot.${RESET}"
else
  warn "The service is not active. Recent log:"
  $SUDO journalctl -u "$SERVICE_NAME" -n 25 --no-pager || true
fi

cat <<'HELP'

  Manage it with:

    tbrctl status      show whether it is running
    tbrctl logs        follow the live log (Ctrl+C to exit)
    tbrctl stop        stop the bot
    tbrctl start       start the bot
    tbrctl restart     restart the bot
    tbrctl config      change tokens / channels, then restart
    tbrctl update      git pull + reinstall dependencies + restart
    tbrctl uninstall   remove the service (keeps your files and .env)

HELP
