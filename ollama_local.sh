#!/bin/bash
# =============================================================================
# Sentinel AI Backend Setup
# Podporuje: Ollama (CPU/GPU) + Raspberry Pi AI HAT+ (Hailo-8 / Hailo-8L)
# =============================================================================
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'

info()    { echo -e "${CYAN}[*]${NC} $*"; }
ok()      { echo -e "${GREEN}[+]${NC} $*"; }
warn()    { echo -e "${YELLOW}[!]${NC} $*"; }
err()     { echo -e "${RED}[x]${NC} $*"; }
section() { echo -e "\n${BOLD}${CYAN}=== $* ===${NC}"; }

# =============================================================================
# 1. DETEKCE SYSTÉMU
# =============================================================================
section "Detekce systému"

OS_TYPE=$(grep -i ^ID= /etc/os-release | cut -d= -f2 | tr -d '"')
ARCH=$(uname -m)
IS_RPI5=false
HAILO_DETECTED=false
HAILO_CHIP="unknown"
HAILO_TOPS=0

info "Systém: $OS_TYPE | Architektura: $ARCH"

if [[ -f /proc/device-tree/model ]]; then
    RPI_MODEL=$(cat /proc/device-tree/model 2>/dev/null | tr -d '\0' || echo "")
    if echo "$RPI_MODEL" | grep -qi "raspberry pi 5"; then
        IS_RPI5=true
        ok "Raspberry Pi 5 detekován: $RPI_MODEL"
    fi
fi

# =============================================================================
# 2. DETEKCE AI HAT+ (Hailo NPU)
# =============================================================================
section "Skenování AI HAT+ / Hailo NPU"

detect_hailo_chip() {
    # Hailo vendor ID v PCI sběrnici: 0x1e60
    local hailo_vendor="1e60"
    # Hailo-8 device ID: 0x0001  |  Hailo-8L device ID: 0x0004
    local hailo8_dev="0001"
    local hailo8l_dev="0004"

    # Prioritní detekce přes lspci
    if command -v lspci &>/dev/null; then
        local pci_out
        pci_out=$(lspci -nn 2>/dev/null)
        if echo "$pci_out" | grep -qi "hailo"; then
            if echo "$pci_out" | grep -q "${hailo_vendor}:${hailo8_dev}"; then
                HAILO_CHIP="hailo8"; HAILO_TOPS=26
            elif echo "$pci_out" | grep -q "${hailo_vendor}:${hailo8l_dev}"; then
                HAILO_CHIP="hailo8l"; HAILO_TOPS=13
            else
                HAILO_CHIP="hailo8l"; HAILO_TOPS=13  # default pro AI HAT+ 2
            fi
            HAILO_DETECTED=true; return
        fi
    fi

    # Fallback: /sys bus přes vendor ID
    if find /sys/bus/pci/devices/*/vendor 2>/dev/null \
         -exec grep -lq "0x${hailo_vendor}" {} \; | grep -q .; then
        HAILO_DETECTED=true
        local dev_id
        dev_id=$(find /sys/bus/pci/devices/*/vendor 2>/dev/null \
                    -exec grep -l "0x${hailo_vendor}" {} \; \
                    | head -1 | xargs dirname 2>/dev/null)/device
        local did
        did=$(cat "$dev_id" 2>/dev/null | tr -d '0x' || echo "")
        if [[ "$did" == "$hailo8_dev" ]]; then
            HAILO_CHIP="hailo8"; HAILO_TOPS=26
        else
            HAILO_CHIP="hailo8l"; HAILO_TOPS=13
        fi
        return
    fi

    # Fallback: /dev/hailo* chardev (driver již načten)
    if ls /dev/hailo* 2>/dev/null | grep -q .; then
        HAILO_DETECTED=true
        HAILO_CHIP="hailo8l"; HAILO_TOPS=13
        return
    fi

    # Fallback: lsmod
    if lsmod 2>/dev/null | grep -q "^hailo_pci"; then
        HAILO_DETECTED=true
        HAILO_CHIP="hailo8l"; HAILO_TOPS=13
    fi
}

detect_hailo_chip

if $HAILO_DETECTED; then
    ok "AI HAT+ detekován: ${HAILO_CHIP} (${HAILO_TOPS} TOPS)"
else
    info "AI HAT+ / Hailo NPU nebyl detekován — bude použita pouze Ollama (CPU)."
fi

# =============================================================================
# 3. INSTALACE ZÁVISLOSTÍ
# =============================================================================
section "Instalace systémových závislostí"

if [[ "$OS_TYPE" == "ubuntu" || "$OS_TYPE" == "debian" || "$OS_TYPE" == "raspbian" ]]; then
    info "Aktualizace balíčků (Debian/Ubuntu)..."
    sudo apt-get update -y
    sudo apt-get install -y curl zstd pciutils lshw
elif [[ "$OS_TYPE" =~ ^(rhel|centos|almalinux|fedora|rocky)$ ]]; then
    info "Instalace závislostí (RHEL/CentOS/Fedora)..."
    sudo yum install -y curl zstd pciutils
else
    warn "Nepodporovaná distribuce, zkouším apt/yum..."
    sudo apt-get install -y curl zstd pciutils 2>/dev/null || \
    sudo yum install -y curl zstd pciutils
fi

# =============================================================================
# 4. NASTAVENÍ AI HAT+ / HAILO (pokud byl detekován)
# =============================================================================
if $HAILO_DETECTED; then
    section "Instalace Hailo Runtime (hailo-all)"

    if dpkg -l hailo-all 2>/dev/null | grep -q "^ii"; then
        ok "hailo-all je již nainstalován."
    else
        info "Instaluji hailo-all — full stack (driver + HailoRT + Python bindings)..."
        sudo apt-get install -y hailo-all || {
            err "hailo-all nenalezen v repo. Přidávám Raspberry Pi APT zdroj..."
            # Standardní cesta pro RPi OS Bookworm
            sudo apt-get install -y rpi-hailo-all 2>/dev/null || {
                warn "Automatická instalace selhala."
                warn "Proveď ručně: sudo apt install hailo-all"
                warn "Viz: https://github.com/hailo-ai/hailo-rpi5-examples"
            }
        }
    fi

    # Ověření instalace přes hailortcli
    if command -v hailortcli &>/dev/null; then
        ok "HailoRT CLI nainstalován: $(hailortcli --version 2>/dev/null || echo 'ok')"
        info "Identifikace zařízení:"
        hailortcli fw-control identify 2>/dev/null || \
            warn "Nelze identifikovat — zkus po restartu (driver potřebuje reboot)."
    fi

    # Přidání uživatele do skupiny hailo
    HAILO_USER="${SUDO_USER:-$(logname 2>/dev/null || echo root)}"
    if getent group hailo &>/dev/null; then
        sudo usermod -aG hailo "$HAILO_USER" 2>/dev/null && \
            ok "Uživatel '$HAILO_USER' přidán do skupiny hailo."
    fi

    # Ověření /dev/hailo0
    if ls /dev/hailo0 2>/dev/null; then
        ok "/dev/hailo0 dostupný — NPU je aktivní."
    else
        warn "/dev/hailo0 není dostupný. Nutný reboot pro načtení PCIe driveru."
        NEED_REBOOT=true
    fi
fi

# =============================================================================
# 5. INSTALACE OLLAMA
# =============================================================================
section "Instalace Ollama (LLM backend)"

if command -v ollama &>/dev/null; then
    ok "Ollama je již nainstalována: $(ollama --version 2>/dev/null)"
else
    info "Stahování a instalace Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    sleep 5
fi

# Zajistit běh služby
if ! systemctl is-active --quiet ollama 2>/dev/null; then
    info "Spouštím ollama.service..."
    sudo systemctl enable --now ollama 2>/dev/null || true
    sleep 5
fi

# =============================================================================
# 6. STAŽENÍ MODELŮ
# =============================================================================
section "Stahování AI modelů"

# Na RPi5 volíme modely podle dostupné RAM
RAM_GB=$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo 2>/dev/null || echo 4)
info "Detekovaná RAM: ~${RAM_GB} GB"

if [[ $RAM_GB -ge 8 ]]; then
    LLM_MODEL="llama3.2:3b"
    info "8+ GB RAM: stahuji llama3.2:3b"
else
    LLM_MODEL="llama3.2:1b"
    info "Méně než 8 GB RAM: stahuji llama3.2:1b (optimalizováno pro RPi5)"
fi

ollama pull "$LLM_MODEL"
ollama pull nomic-embed-text
ok "Modely staženy: ${LLM_MODEL}, nomic-embed-text"

# =============================================================================
# 7. KONFIGURACE SENTINELU
# =============================================================================
section "Konfigurace Sentinelu"

CONFIG_FILE="/etc/sentinel/config.yaml"
CONFIG_LOCAL="/opt/Sentinel/config.yaml"

# Použít existující config nebo zkusit lokální fallback
[[ -f "$CONFIG_FILE" ]] || CONFIG_FILE="$CONFIG_LOCAL"

if [[ -f "$CONFIG_FILE" ]]; then
    info "Aktualizuji $CONFIG_FILE..."
    cp "$CONFIG_FILE" "${CONFIG_FILE}.bak"

    sed -i "s/ollama_model:.*/ollama_model: \"${LLM_MODEL}\"/" "$CONFIG_FILE"
    sed -i "s|ollama_url:.*|ollama_url: \"http://localhost:11434/v1/chat/completions\"|" "$CONFIG_FILE"

    # RPi5 optimalizace: 1 AI worker vlákno (zabrání OOM)
    sed -i "s/worker_threads:.*/worker_threads: 1/" "$CONFIG_FILE"

    # AI HAT+ sekce
    if $HAILO_DETECTED; then
        if grep -q "ai_hat:" "$CONFIG_FILE"; then
            # Aktualizace existující sekce
            sed -i "/^ai_hat:/,/^[^ ]/ s/enabled:.*/enabled: true/" "$CONFIG_FILE"
            sed -i "/^ai_hat:/,/^[^ ]/ s/device:.*/device: \"${HAILO_CHIP}\"/" "$CONFIG_FILE"
        else
            # Přidání nové sekce na konec
            cat >> "$CONFIG_FILE" <<EOF

ai_hat:
  enabled: true
  device: "${HAILO_CHIP}"
  tops: ${HAILO_TOPS}
  hef_model_path: ""
  use_for_embeddings: false
EOF
        fi
        ok "AI HAT+ konfigurace přidána do $CONFIG_FILE (device: ${HAILO_CHIP}, ${HAILO_TOPS} TOPS)"
    fi

    ok "Konfigurace aktualizována: $CONFIG_FILE"
else
    warn "Config soubor nenalezen. Spusť sentinel_init.py pro vytvoření konfigurace."
fi

# =============================================================================
# 8. FINÁLNÍ REPORT
# =============================================================================
section "Výsledek instalace"

echo ""
echo "  Ollama:        $(command -v ollama &>/dev/null && echo "OK ($(ollama --version 2>/dev/null))" || echo "CHYBA")"
echo "  Ollama service: $(systemctl is-active ollama 2>/dev/null || echo 'neznámý')"
echo "  LLM model:     $LLM_MODEL"
echo "  Embed model:   nomic-embed-text"
if $HAILO_DETECTED; then
    echo "  AI HAT+:       ${HAILO_CHIP} (${HAILO_TOPS} TOPS)"
    echo "  HailoRT CLI:   $(command -v hailortcli &>/dev/null && echo "OK" || echo "není v PATH")"
    echo "  /dev/hailo0:   $(ls /dev/hailo0 2>/dev/null && echo "AKTIVNÍ" || echo "čeká na reboot")"
else
    echo "  AI HAT+:       nedetekován (CPU mode)"
fi
echo ""

if ${NEED_REBOOT:-false}; then
    warn "Hailo PCIe driver vyžaduje REBOOT pro aktivaci /dev/hailo0."
    warn "Po rebootu spusť: hailortcli scan"
fi

echo ""
ok "Hotovo! Spuštění Sentinelu: python3 -m sentinel"
