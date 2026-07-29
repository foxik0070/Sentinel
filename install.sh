#!/bin/bash
# Sentinel Commander — Installation script
# Supports: Debian/Ubuntu, RHEL/Rocky/AlmaLinux 8–10, Raspberry Pi OS
set -e

SENTINEL_DIR="${SENTINEL_DIR:-/opt/Sentinel}"
CONFIG_FILE="/etc/sentinel/config.yaml"
SERVICE_FILE="/etc/systemd/system/sentinel.service"
SENTINEL_USER="${SUDO_USER:-$(whoami)}"

# ── Colors ────────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERR]${NC}   $*"; exit 1; }
info() { echo -e "        $*"; }
hdr()  { echo -e "${CYAN}$*${NC}"; }

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    Sentinel Commander — Installation     ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Language selection ────────────────────────────────────────────────────────
hdr "Choose language / Zvolte jazyk:"
echo "  1) English"
echo "  2) Čeština (Czech)"
echo ""
read -rp "Language [1/2, default: 1]: " LANG_CHOICE
case "${LANG_CHOICE:-1}" in
    2) LANG=cs ;;
    *) LANG=en ;;
esac

# Text strings
if [ "$LANG" = "cs" ]; then
    T_STEP_DEPS="[1/6] Instalace systémových závislostí..."
    T_STEP_DIR="[2/6] Příprava pracovního adresáře..."
    T_STEP_PY="[3/6] Instalace Python závislostí..."
    T_STEP_HAILO="[3b] Detekce Hailo AI HAT 2+..."
    T_STEP_DIRS="[4/6] Vytváření adresářů..."
    T_STEP_CFG="[5/6] Konfigurace..."
    T_STEP_SVC="[6/6] Systemd service..."
    T_CFG_TITLE="=== Interaktivní konfigurace ==="
    T_CFG_INST="Název instance (zobrazí se v UI záhlaví)"
    T_CFG_PORT="Port webového rozhraní"
    T_CFG_USER="Uživatelské jméno administrátora"
    T_CFG_PASS="Heslo administrátora"
    T_CFG_VIEWER_PASS="Heslo pro prohlížeče (viewer)"
    T_CFG_SKIP="(Enter = ponechat výchozí)"
    T_DONE="=== Instalace dokončena ==="
    T_NEXT="Další kroky:"
    T_NEXT1="1. Zkontroluj/uprav konfiguraci:"
    T_NEXT2="2. Test spuštění:"
    T_NEXT3="3. Jako systemd služba:"
    T_NEXT4="4. Ověření:"
    T_UI="Sentinel Web UI (po spuštění):"
else
    T_STEP_DEPS="[1/6] Installing system dependencies..."
    T_STEP_DIR="[2/6] Preparing working directory..."
    T_STEP_PY="[3/6] Installing Python dependencies..."
    T_STEP_HAILO="[3b] Detecting Hailo AI HAT 2+..."
    T_STEP_DIRS="[4/6] Creating directories..."
    T_STEP_CFG="[5/6] Configuration..."
    T_STEP_SVC="[6/6] Systemd service..."
    T_CFG_TITLE="=== Interactive configuration ==="
    T_CFG_INST="Instance name (shown in the UI header)"
    T_CFG_PORT="Web UI port"
    T_CFG_USER="Administrator username"
    T_CFG_PASS="Administrator password"
    T_CFG_VIEWER_PASS="Viewer password"
    T_CFG_SKIP="(Enter = keep default)"
    T_DONE="=== Installation complete ==="
    T_NEXT="Next steps:"
    T_NEXT1="1. Review/edit configuration:"
    T_NEXT2="2. Test run:"
    T_NEXT3="3. As a systemd service:"
    T_NEXT4="4. Verify:"
    T_UI="Sentinel Web UI (after start):"
fi

echo ""

# ── OS detection ──────────────────────────────────────────────────────────────
detect_os() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        OS_ID="${ID:-linux}"
        OS_VER="${VERSION_ID:-0}"
    else
        OS_ID="linux"; OS_VER="0"
    fi
}
detect_os

# ── 1. System dependencies ────────────────────────────────────────────────────
hdr "$T_STEP_DEPS"

case "$OS_ID" in
    debian|ubuntu|raspbian)
        sudo apt-get update -q
        sudo apt-get install -y --no-install-recommends \
            python3 python3-pip python3-dev python3-venv \
            build-essential git curl libssl-dev libffi-dev
        ok "apt packages installed"
        ;;
    rhel|centos|rocky|almalinux|fedora)
        sudo dnf update -y -q
        sudo dnf install -y gcc gcc-c++ python3-devel git curl
        if [[ "$OS_VER" == 8* ]]; then
            sudo dnf install -y python39 python39-devel
            warn "RHEL 8: use python3.9 instead of python3"
        fi
        ok "dnf packages installed"
        ;;
    *)
        warn "Unknown OS ($OS_ID) — skipping system packages."
        info "Ensure manually: python3, python3-dev, build-essential/gcc"
        ;;
esac

# ── 2. Working directory ──────────────────────────────────────────────────────
hdr "$T_STEP_DIR"

if [ ! -d "$SENTINEL_DIR" ]; then
    err "Directory $SENTINEL_DIR does not exist. Set SENTINEL_DIR variable."
fi
cd "$SENTINEL_DIR"
ok "Working directory: $SENTINEL_DIR"

# ── 3. Python dependencies ────────────────────────────────────────────────────
hdr "$T_STEP_PY"

PYTHON_BIN="python3"
if command -v python3.9 &>/dev/null && [[ "$OS_ID" == "rhel" && "$OS_VER" == 8* ]]; then
    PYTHON_BIN="python3.9"
fi

if [ -f "$SENTINEL_DIR/setup.py" ]; then
    sudo "$PYTHON_BIN" -m pip install -e "$SENTINEL_DIR" --break-system-packages -q
    ok "Python package installed (pip install -e .)"
else
    err "setup.py not found in $SENTINEL_DIR"
fi

sudo "$PYTHON_BIN" -m pip install paho-mqtt --break-system-packages -q
ok "paho-mqtt installed"

# ── 3b. Hailo AI HAT 2+ detection ────────────────────────────────────────────
hdr "$T_STEP_HAILO"

HAILO10H_DETECTED=false
HAILO_OLLAMA_DETECTED=false

if lsmod 2>/dev/null | grep -q "hailo1x_pci" || ls /sys/module/hailo1x_pci &>/dev/null; then
    HAILO10H_DETECTED=true
    ok "Hailo-10H (AI HAT 2+) detected: /sys/module/hailo1x_pci"
fi
if [ -e /dev/hailo0 ]; then
    ok "Hailo-8/8L detected: /dev/hailo0"
fi
if command -v hailo-ollama &>/dev/null || systemctl list-unit-files 2>/dev/null | grep -q "hailo-ollama"; then
    HAILO_OLLAMA_DETECTED=true
    ok "hailo-ollama found — NPU LLM inference available"
    if systemctl is-active --quiet hailo-ollama 2>/dev/null; then
        ok "hailo-ollama.service is running"
    else
        warn "hailo-ollama.service is not running — start: sudo systemctl start hailo-ollama"
    fi
else
    if [ "$HAILO10H_DETECTED" = true ]; then
        warn "Hailo-10H detected, but hailo-ollama not found."
        info "Install hailo-ollama 5.3.0+ and set hailo_ollama.enabled: true in config."
    fi
fi
if command -v ollama &>/dev/null; then
    if ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
        ok "nomic-embed-text embedding model found"
    else
        warn "nomic-embed-text not found — RAG will be disabled."
        info "  ollama pull nomic-embed-text"
    fi
fi

# ── 4. Directories and permissions ────────────────────────────────────────────
hdr "$T_STEP_DIRS"

for dir in /etc/sentinel /var/log/sentinel/logs /opt/Sentinel/data /opt/Sentinel/learning_knowledge_base; do
    sudo mkdir -p "$dir"
    sudo chown "$SENTINEL_USER:$SENTINEL_USER" "$dir"
    ok "Directory: $dir"
done

# ── 5. Configuration ──────────────────────────────────────────────────────────
hdr "$T_STEP_CFG"

CONFIG_IS_NEW=false
if [ ! -f "$CONFIG_FILE" ]; then
    if [ -f "$SENTINEL_DIR/config.yaml.example" ]; then
        sudo cp "$SENTINEL_DIR/config.yaml.example" "$CONFIG_FILE"
        sudo chown "$SENTINEL_USER:$SENTINEL_USER" "$CONFIG_FILE"
        CONFIG_IS_NEW=true
        ok "Config copied from example: $CONFIG_FILE"
    else
        warn "config.yaml.example not found — create manually: $CONFIG_FILE"
    fi
else
    ok "Config exists: $CONFIG_FILE"
fi

# ── Interactive configuration (only on fresh install) ─────────────────────────
if [ "$CONFIG_IS_NEW" = true ]; then
    echo ""
    hdr "$T_CFG_TITLE"
    info "$T_CFG_SKIP"
    echo ""

    # Instance name
    echo -e "  ${CYAN}${T_CFG_INST}${NC}"
    info "  Example: HOME, OFFICE, LAB"
    read -rp "  Instance name [HOME]: " CFG_INST
    CFG_INST="${CFG_INST:-HOME}"

    # Port
    echo ""
    echo -e "  ${CYAN}${T_CFG_PORT}${NC}"
    read -rp "  Port [5050]: " CFG_PORT
    CFG_PORT="${CFG_PORT:-5050}"

    # Admin username
    echo ""
    echo -e "  ${CYAN}${T_CFG_USER}${NC}"
    read -rp "  Username [admin]: " CFG_USER
    CFG_USER="${CFG_USER:-admin}"

    # Admin password
    echo ""
    echo -e "  ${CYAN}${T_CFG_PASS}${NC}"
    info "  Min 8 characters. Will be stored in $CONFIG_FILE"
    while true; do
        read -rsp "  Password: " CFG_PASS; echo ""
        read -rsp "  Confirm:  " CFG_PASS2; echo ""
        [ "$CFG_PASS" = "$CFG_PASS2" ] && [ ${#CFG_PASS} -ge 8 ] && break
        warn "Passwords don't match or too short (min 8 chars). Try again."
    done

    # Viewer password
    echo ""
    echo -e "  ${CYAN}${T_CFG_VIEWER_PASS}${NC}"
    read -rsp "  Viewer password [viewer]: " CFG_VIEWER_PASS; echo ""
    CFG_VIEWER_PASS="${CFG_VIEWER_PASS:-viewer}"

    # Secret key
    CFG_SECRET=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || \
                 head -c 32 /dev/urandom | xxd -p | tr -d '\n')

    # Apply to config file
    sed -i "s/^instance_name:.*/instance_name: ${CFG_INST}/" "$CONFIG_FILE"
    sed -i "s/^  port:.*/  port: ${CFG_PORT}/" "$CONFIG_FILE"
    sed -i "s/^  username:.*/  username: ${CFG_USER}/" "$CONFIG_FILE"
    sed -i "s/^  password: CHANGE_ME/  password: ${CFG_PASS}/" "$CONFIG_FILE"
    sed -i "s|^  secret_key:.*|  secret_key: ${CFG_SECRET}|" "$CONFIG_FILE"
    sed -i "s/^  viewer_password:.*/  viewer_password: ${CFG_VIEWER_PASS}/" "$CONFIG_FILE"

    echo ""
    ok "Configuration written to $CONFIG_FILE"
    warn "Review and adjust AI/LDAP/integrations settings manually before starting."
fi

# ── 6. Systemd service ────────────────────────────────────────────────────────
hdr "$T_STEP_SVC"

if [ -f "$SERVICE_FILE" ]; then
    ok "Service file exists: $SERVICE_FILE"
else
    cat | sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=Sentinel Commander - System Monitor
After=network.target network-online.target syslog.target
Wants=network-online.target

[Service]
Type=notify
User=$SENTINEL_USER
Group=$SENTINEL_USER
WorkingDirectory=$SENTINEL_DIR
ExecStart=/usr/bin/python3 -m sentinel
Environment="PYTHONUNBUFFERED=1"
Environment="PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
WatchdogSec=60
Restart=always
RestartSec=10
NoNewPrivileges=yes
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF
    ok "Service file created: $SERVICE_FILE"
fi

sudo systemctl daemon-reload
ok "Systemd daemon reloaded"

# ── Logrotate ─────────────────────────────────────────────────────────────────
LOGROTATE_CONF="/etc/logrotate.d/sentinel"
if [ ! -f "$LOGROTATE_CONF" ]; then
    sudo tee "$LOGROTATE_CONF" > /dev/null <<'LOGROTATE_EOF'
/var/log/sentinel/sentinel.log
/var/log/sentinel/sentinel-ollama.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su root root
}
LOGROTATE_EOF
    ok "Logrotate config created: $LOGROTATE_CONF"
else
    ok "Logrotate config already exists: $LOGROTATE_CONF"
fi

# ── Verify installation ────────────────────────────────────────────────────────
echo ""
echo "=== Verification ==="
bash "$SENTINEL_DIR/check.sh" 2>/dev/null | grep -E "\[OK\]|\[CHYBI\]|\[MISSING\]" || true

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════╗"
echo "║    $T_DONE    ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "$T_NEXT"
echo ""
echo "  $T_NEXT1"
echo "     nano $CONFIG_FILE"
echo ""
echo "  $T_NEXT2"
echo "     cd $SENTINEL_DIR && python3 -m sentinel"
echo ""
echo "  $T_NEXT3"
echo "     sudo systemctl enable --now sentinel"
echo "     sudo systemctl status sentinel"
echo "     journalctl -u sentinel -f"
echo ""
echo "  $T_NEXT4"
echo "     bash $SENTINEL_DIR/check.sh"
echo ""
echo "  $T_UI"
echo "     http://$(hostname -I | awk '{print $1}' 2>/dev/null || echo 'localhost'):${CFG_PORT:-5050}"
echo ""
