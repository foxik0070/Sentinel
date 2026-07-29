#!/usr/bin/env python3

import json
import os
import urllib.request
import curses
import time

# --- SYSTEM CONFIGURATION ---
HAILO_URL = "http://127.0.0.1:8000"

# --- EXPANDED NEURAL DATABASE ---
MODEL_DB = {
    "deepseek_r1:1.5b": {
        "type": "Logic", "size": "2.37G", "tps": "7.9", 
        "release": "Q1 2026", "ctx": "2048", "focus": "Reasoning & Math", 
        "detail": "Pokrocily model vyuzivajici RL (Reinforcement Learning) pro slozite logicke uvazovani a hlubokou analyzu."
    },
    "deepseek_r1_distill_qwen:1.5b": {
        "type": "DistLogic", "size": "2.37G", "tps": "7.9", 
        "release": "Q1 2026", "ctx": "2048", "focus": "Fast Reasoning", 
        "detail": "Odlehcena 'distilled' verze reasoning modelu, optimalizovana na maximalni vykon a rychlou dedukci."
    },
    "llama3.2:1b": {
        "type": "LLM", "size": "1.79G", "tps": "9.8", 
        "release": "Q4 2025", "ctx": "2048", "focus": "General Chat", 
        "detail": "Kompaktni a vysoce efektivni model od Mety, idealni pro bleskove odpovedi a plynulou konverzaci."
    },
    "llama3.2:3b": {
        "type": "LLM", "size": "3.20G", "tps": "4.5", 
        "release": "Q4 2025", "ctx": "2048", "focus": "Complex Chat", 
        "detail": "Vetsi bratr 1B verze s vice parametry, nabizi lepsi pochopeni kontextu na ukor mirne nizsi rychlosti."
    },
    "qwen2.5-coder:1.5b": {
        "type": "Coder", "size": "1.64G", "tps": "8.1", 
        "release": "Q1 2026", "ctx": "2048", "focus": "Programming", 
        "detail": "Specializovana architektura zamerena vyhradne na generovani, opravu a analyzu zdrojoveho kodu."
    },
    "qwen3:1.7b": {
        "type": "Chat", "size": "1.79G", "tps": "4.7", 
        "release": "Q2 2026", "ctx": "2048", "focus": "General Chat", 
        "detail": "Spickovy konverzacni model nove generace. Aktualne nejlepsi volba pro bezne chatovani a textove ulohy."
    },
    "qwen2.5:1.5b": {
        "type": "LLM", "size": "1.64G", "tps": "7.3", 
        "release": "Q1 2026", "ctx": "2048", "focus": "General Purpose", 
        "detail": "Vylepseny stabilni Qwen model. Skvely balanc mezi rychlosti zpracovani a kvalitou psaneho textu."
    },
    "qwen2.5-instruct:1.5b": {
        "type": "Instruct", "size": "1.64G", "tps": "7.3", 
        "release": "Q1 2026", "ctx": "2048", "focus": "Task Execution", 
        "detail": "Model natrenovany striktne na plneni primych prikazu a instrukci uzivatele."
    },
    "qwen2:1.5b": {
        "type": "LLM", "size": "1.56G", "tps": "8.0", 
        "release": "Q3 2025", "ctx": "2048", "focus": "Legacy Chat", 
        "detail": "Spolehlivy a stabilni predchudce rodiny Qwen. Velmi rychly a pametove usporny."
    },
    "qwen2-1.5b-instruct-function-calling-v1": {
        "type": "Agent", "size": "2.99G", "tps": "6.6", 
        "release": "Q1 2026", "ctx": "2048", "focus": "API & Tools", 
        "detail": "Specialka pro volani externich skriptu a API. Fine-tuned specifiky na rozsahlem VIGGO datasetu."
    },
    "qwen2-vl-2b-instruct": {
        "type": "Vision", "size": "2.18G", "tps": "7.0", 
        "release": "Q1 2026", "ctx": "2048", "focus": "Image Analysis", 
        "detail": "Multimodalni system s vision encoderem, schopny cist a analyzovat obrazy i text zaroven."
    },
    "qwen3-vl-2b-instruct": {
        "type": "Vision", "size": "2.18G", "tps": "4.7", 
        "release": "Q2 2026", "ctx": "2048", "focus": "Video/Image", 
        "detail": "Novejsi vize-textovy model s podporou analyzy video obsahu a vylepsenym pochopenim sceny."
    },
    "whisper-tiny": {
        "type": "Audio", "size": "78M", "tps": "48.1", 
        "release": "2024", "ctx": "N/A", "focus": "Speech-to-Text", 
        "detail": "Extremne maly a bleskovy transformer model pro prevod mluveneho slova na text."
    },
    "whisper-base": {
        "type": "Audio", "size": "155M", "tps": "25.3", 
        "release": "2024", "ctx": "N/A", "focus": "Speech-to-Text", 
        "detail": "Zakladni Whisper model poskytujici lepsi presnost rozpoznavani zvuku pri stale vysoke rychlosti."
    },
    "whisper-small": {
        "type": "Audio", "size": "388M", "tps": "10.6", 
        "release": "2024", "ctx": "N/A", "focus": "Speech-to-Text", 
        "detail": "Robustni model pro prevod mluveneho slova zachycujici vysoky detail a slozitejsi intonaci."
    }
}

DEFAULT_MODEL = {
    "type": "Unknown", "size": "N/A", "size_gb": 0.0, "tps": 0.0,
    "release": "N/A", "ctx": "N/A", "focus": "N/A",
    "detail": "Specifikace k tomuto modulu nejsou v lokalni databazi k dispozici."
}

# Normalize MODEL_DB: convert tps str→float, add size_gb
def _parse_size_gb(s):
    try:
        s = str(s).strip().upper()
        if s.endswith('G'): return float(s[:-1])
        if s.endswith('M'): return float(s[:-1]) / 1024.0
        return float(s)
    except Exception: return 0.0

for _name, _det in MODEL_DB.items():
    if isinstance(_det.get('tps'), str):
        try: _det['tps'] = float(_det['tps'])
        except ValueError: _det['tps'] = 0.0
    if 'size_gb' not in _det:
        _det['size_gb'] = _parse_size_gb(_det.get('size', '0'))

TYPE_COLORS = {
    'Logic':    curses.COLOR_CYAN    if hasattr(curses, 'COLOR_CYAN')    else 6,
    'DistLogic':curses.COLOR_CYAN    if hasattr(curses, 'COLOR_CYAN')    else 6,
    'LLM':      curses.COLOR_GREEN   if hasattr(curses, 'COLOR_GREEN')   else 2,
    'Coder':    curses.COLOR_YELLOW  if hasattr(curses, 'COLOR_YELLOW')  else 3,
    'Chat':     curses.COLOR_BLUE    if hasattr(curses, 'COLOR_BLUE')    else 4,
    'Instruct': curses.COLOR_MAGENTA if hasattr(curses, 'COLOR_MAGENTA') else 5,
    'Agent':    curses.COLOR_RED     if hasattr(curses, 'COLOR_RED')     else 1,
    'Vision':   curses.COLOR_WHITE   if hasattr(curses, 'COLOR_WHITE')   else 7,
    'Audio':    curses.COLOR_CYAN    if hasattr(curses, 'COLOR_CYAN')    else 6,
    'Unknown':  curses.COLOR_WHITE   if hasattr(curses, 'COLOR_WHITE')   else 7,
}

def bar(pct, width=10):
    """Simple block-char progress bar: '█' filled, '░' empty."""
    filled = max(0, min(width, int(round(pct / 100.0 * width))))
    return '█' * filled + '░' * (width - filled)

def disk_usage_mb(models_dir=None):
    """Returns total size in MB of .hef files in models_dir."""
    if models_dir is None:
        models_dir = os.environ.get('HAILO_MODELS_DIR', '/usr/share/hailo-models')
    total = 0.0
    try:
        for fname in os.listdir(models_dir):
            fpath = os.path.join(models_dir, fname)
            if os.path.isfile(fpath):
                total += os.path.getsize(fpath)
    except Exception:
        pass
    return total / (1024 * 1024)

def get_hailo_service_status(url='http://localhost:8000/api/tags'):
    """Returns True if hailo-ollama service is reachable, False otherwise."""
    try:
        urllib.request.urlopen(url, timeout=2)
        return True
    except Exception:
        return False

# Global state for HW monitoring
last_cpu = {'idle': 0, 'total': 0}
net_state = {'rx': 0, 'tx': 0, 'time': time.time()}

def safe_addstr(stdscr, y, x, string, attr=0):
    """Safely write to curses avoiding out-of-bounds errors."""
    try:
        height, width = stdscr.getmaxyx()
        if y < height and x < width:
            stdscr.addstr(y, x, string[:width-x-1], attr)
    except curses.error:
        pass

def get_sys_stats():
    """Reads native Linux HW stats (CPU, RAM, Uptime)."""
    global last_cpu
    try:
        with open('/proc/stat') as f:
            line = f.readline().split()
        idle = int(line[4]) + int(line[5])
        total = sum(int(x) for x in line[1:8])
        diff_idle = idle - last_cpu['idle']
        diff_total = total - last_cpu['total']
        cpu_pct = 0.0
        if diff_total > 0:
            cpu_pct = 100.0 * (diff_total - diff_idle) / diff_total
        last_cpu['idle'] = idle
        last_cpu['total'] = total
    except:
        cpu_pct = 0.0

    try:
        with open('/proc/meminfo') as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            parts = line.split()
            mem[parts[0].strip(':')] = int(parts[1])
        total_ram = mem.get('MemTotal', 1) / 1024
        avail_ram = mem.get('MemAvailable', mem.get('MemFree', 1)) / 1024
        used_ram = total_ram - avail_ram
        ram_pct = (used_ram / total_ram) * 100.0
    except:
        total_ram = 1; used_ram = 0; ram_pct = 0.0
        
    try:
        with open('/proc/uptime') as f:
            up_sec = float(f.readline().split()[0])
            mins, secs = divmod(up_sec, 60)
            hours, mins = divmod(mins, 60)
            uptime = f"{int(hours):02}:{int(mins):02}:{int(secs):02}"
    except:
        uptime = "00:00:00"

    return cpu_pct, used_ram, total_ram, ram_pct, uptime

def get_net_stats():
    """Reads network interface bytes to calculate speed."""
    global net_state
    rx = 0; tx = 0
    try:
        with open('/proc/net/dev') as f:
            lines = f.readlines()[2:]
        for line in lines:
            parts = line.split()
            iface = parts[0].strip(':')
            if iface != 'lo':
                rx += int(parts[1])
                tx += int(parts[9]) if len(parts)>9 else 0
    except:
        pass
    
    now = time.time()
    dt = now - net_state['time']
    rx_spd = 0.0; tx_spd = 0.0
    if dt > 0:
        rx_spd = (rx - net_state['rx']) / dt / (1024*1024)
        tx_spd = (tx - net_state['tx']) / dt / (1024*1024)
    
    net_state['rx'] = rx
    net_state['tx'] = tx
    net_state['time'] = now
    
    return rx_spd, tx_spd

def draw_htop_bar(stdscr, y, x, label, pct, val_str, width, color):
    """Draws classic htop progress bar."""
    safe_addstr(stdscr, y, x, f"{label:<3}[", curses.color_pair(5) | curses.A_BOLD)
    bar_len = width - len(label) - len(val_str) - 4
    if bar_len < 1: bar_len = 1
    
    filled = int((pct / 100.0) * bar_len)
    empty = bar_len - filled
    
    safe_addstr(stdscr, y, x + len(label) + 1, "|" * filled, color | curses.A_BOLD)
    safe_addstr(stdscr, y, x + len(label) + 1 + filled, " " * empty, curses.color_pair(5))
    safe_addstr(stdscr, y, x + len(label) + 1 + bar_len, f"{val_str:>7}]", curses.color_pair(5))

def draw_top_stats(stdscr, width):
    """Draws CPU, RAM and Network stats."""
    cpu_pct, used_ram, total_ram, ram_pct, uptime = get_sys_stats()
    rx_spd, tx_spd = get_net_stats()

    bar_w = int(width * 0.45)
    draw_htop_bar(stdscr, 0, 1, "CPU", cpu_pct, f"{cpu_pct:4.1f}%", bar_w, curses.color_pair(3))
    draw_htop_bar(stdscr, 1, 1, "Mem", ram_pct, f"{int(used_ram)}M", bar_w, curses.color_pair(7))

    right_x = bar_w + 5
    safe_addstr(stdscr, 0, right_x, f"Net RX: {rx_spd:6.1f} MB/s", curses.color_pair(6) | curses.A_BOLD)
    safe_addstr(stdscr, 1, right_x, f"Net TX: {tx_spd:6.1f} MB/s", curses.color_pair(6) | curses.A_BOLD)
    safe_addstr(stdscr, 2, right_x, f"Uptime: {uptime}", curses.color_pair(5))

def draw_box(stdscr, y, x, h, w, title):
    """Draws an ASCII box overlay."""
    safe_addstr(stdscr, y, x, "+" + "-"*(w-2) + "+", curses.color_pair(5))
    safe_addstr(stdscr, y, x+2, f" {title} ", curses.color_pair(6) | curses.A_BOLD)
    for i in range(1, h-1):
        safe_addstr(stdscr, y+i, x, "|", curses.color_pair(5))
        safe_addstr(stdscr, y+i, x+w-1, "|", curses.color_pair(5))
        safe_addstr(stdscr, y+i, x+1, " "*(w-2)) # Clear inside
    safe_addstr(stdscr, y+h-1, x, "+" + "-"*(w-2) + "+", curses.color_pair(5))

def action_delete(stdscr, model_name, height, width):
    bw, bh = 50, 6
    bx, by = (width - bw) // 2, (height - bh) // 2
    draw_box(stdscr, by, bx, bh, bw, " Smazani modelu ")
    
    safe_addstr(stdscr, by+2, bx+2, f"Odesilam pozadavek na vymazani:", curses.color_pair(5))
    safe_addstr(stdscr, by+3, bx+2, f"{model_name}", curses.color_pair(4) | curses.A_BOLD)
    stdscr.refresh()
    
    req = urllib.request.Request(f"{HAILO_URL}/api/delete", data=json.dumps({"name": model_name}).encode('utf-8'), headers={'Content-Type': 'application/json'}, method='DELETE')
    try:
        urllib.request.urlopen(req)
        safe_addstr(stdscr, by+4, bx+2, "Model uspesne smazan!", curses.color_pair(3) | curses.A_BOLD)
    except:
        safe_addstr(stdscr, by+4, bx+2, "Chyba pri mazani!", curses.color_pair(4) | curses.A_BOLD)
    stdscr.refresh()
    time.sleep(1)

def action_download(stdscr, model_name, height, width):
    bw, bh = 60, 8
    bx, by = (width - bw) // 2, (height - bh) // 2
    
    req = urllib.request.Request(f"{HAILO_URL}/api/pull", data=json.dumps({"model": model_name, "stream": True}).encode('utf-8'), headers={'Content-Type': 'application/json'})
    
    dl_start_time = time.time()
    last_completed = 0
    dl_speed = 0.0
    last_draw_time = 0

    try:
        with urllib.request.urlopen(req) as response:
            for line in response:
                if not line: continue
                
                now = time.time()
                # Limit UI refresh to ~5 FPS to save CPU
                if now - last_draw_time > 0.2:
                    try:
                        msg = json.loads(line.decode('utf-8'))
                        total = msg.get('total', 0)
                        completed = msg.get('completed', 0)
                        status = msg.get('status', 'unknown')

                        draw_top_stats(stdscr, width) # Keep background stats alive
                        draw_box(stdscr, by, bx, bh, bw, " Prubeh stahovani ")

                        safe_addstr(stdscr, by+1, bx+2, f"Model: {model_name}", curses.color_pair(6) | curses.A_BOLD)

                        if total > 0:
                            percent = int((completed / total) * 100)
                            total_mb = total / (1024 * 1024)
                            comp_mb = completed / (1024 * 1024)
                            
                            # Speed calculation
                            dt = now - dl_start_time
                            if dt > 0.5:
                                dl_speed = (completed - last_completed) / (now - dl_start_time) / (1024*1024)
                                last_completed = completed
                                dl_start_time = now

                            safe_addstr(stdscr, by+2, bx+2, f"Rychlost site/disku: {dl_speed:.1f} MB/s", curses.color_pair(3))
                            
                            bar_len = bw - 14
                            filled = int((percent / 100.0) * bar_len)
                            empty = bar_len - filled
                            bar_str = "=" * filled
                            if empty > 0: bar_str += ">" + " " * (empty - 1)
                            
                            safe_addstr(stdscr, by+4, bx+2, f"[{bar_str}] {percent}%", curses.color_pair(6))
                            safe_addstr(stdscr, by+5, bx+2, f"Stazeno: {comp_mb:.0f} MB / {total_mb:.0f} MB", curses.color_pair(5))
                        else:
                            safe_addstr(stdscr, by+3, bx+2, f"Status: {status}", curses.color_pair(7))

                        stdscr.refresh()
                        last_draw_time = now
                    except:
                        pass
    except Exception as e:
        draw_box(stdscr, by, bx, bh, bw, " Chyba ")
        safe_addstr(stdscr, by+2, bx+2, f"{e}", curses.color_pair(4))
        stdscr.refresh()
        time.sleep(2)
        return

def get_available_models():
    try:
        req = urllib.request.Request(f"{HAILO_URL}/hailo/v1/list")
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.loads(response.read().decode('utf-8')).get('models', [])
    except: return []

def get_downloaded_models():
    try:
        req = urllib.request.Request(f"{HAILO_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=2) as response:
            return [m['name'] for m in json.loads(response.read().decode('utf-8')).get('models', [])]
    except: return []

def tui_main(stdscr):
    curses.start_color()
    curses.use_default_colors()
    
    # Barvy pro texty a grafy
    curses.init_pair(3, curses.COLOR_GREEN, -1)   # Zelene pruhy grafu a data
    curses.init_pair(4, curses.COLOR_RED, -1)     # Cervene upozorneni
    curses.init_pair(5, curses.COLOR_WHITE, -1)   # Zakladni bily text
    curses.init_pair(6, curses.COLOR_CYAN, -1)    # Tyrkysove texty a nadpisy
    curses.init_pair(7, curses.COLOR_YELLOW, -1)  # Zluta barva pro zvyrazneni

    curses.curs_set(0)
    stdscr.timeout(1000)
    
    available = get_available_models()
    downloaded = get_downloaded_models()
    current_row = 0

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # --- SEKCE 1: HTOP HW MONITOR ---
        draw_top_stats(stdscr, width)

        # --- SEKCE 2: HLAVICKA TABULKY ---
        header = f" {'MODEL NAME':<35} {'STATUS':<12} {'SIZE':<8} {'TPS':<6} {'TYPE'} "
        safe_addstr(stdscr, 4, 0, header.ljust(width - 1), curses.A_REVERSE | curses.A_BOLD)

        # --- SEKCE 3: SEZNAM MODELU ---
        list_y_start = 5
        details_height = 7 # Vyska bloku pro detailni informace
        list_max_rows = height - list_y_start - details_height - 1 # 1 pro footer
        if list_max_rows < 3: list_max_rows = 3 # Pojistka pro extra male terminaly
        
        if not available:
            safe_addstr(stdscr, list_y_start, 2, "Cekam na API / Zadne modely nenalezeny...", curses.color_pair(4))
        
        for idx, model in enumerate(available):
            if idx >= list_max_rows: break
            
            y = list_y_start + idx
            is_downloaded = model in downloaded
            status_text = "STAZENO" if is_downloaded else "DOSTUPNE"
            
            details = MODEL_DB.get(model.lower(), DEFAULT_MODEL)
            row_str = f" {model:<35} {status_text:<12} {details['size']:<8} {details['tps']:<6} {details['type']} "
            row_str = row_str.ljust(width - 1)

            if idx == current_row:
                safe_addstr(stdscr, y, 0, row_str, curses.A_REVERSE | curses.A_BOLD)
            else:
                color = curses.color_pair(3) if is_downloaded else curses.color_pair(5)
                safe_addstr(stdscr, y, 0, row_str, color)

        # --- SEKCE 4: DETAILNI PANEL (Dole nad footerem) ---
        details_y_start = height - details_height - 1
        safe_addstr(stdscr, details_y_start, 0, " DETAIL MODELU ".center(width - 1, "-"), curses.color_pair(6) | curses.A_BOLD)
        
        if available and current_row < len(available):
            sel_model = available[current_row]
            det = MODEL_DB.get(sel_model.lower(), DEFAULT_MODEL)
            
            # Prvni radek detailu
            safe_addstr(stdscr, details_y_start + 1, 2, f"Nazev:    ", curses.color_pair(5))
            safe_addstr(stdscr, details_y_start + 1, 12, f"{sel_model}", curses.color_pair(6) | curses.A_BOLD)
            safe_addstr(stdscr, details_y_start + 1, 45, f"Vydani:   {det['release']}", curses.color_pair(5))
            
            # Druhy radek detailu
            safe_addstr(stdscr, details_y_start + 2, 2, f"Zamereni: {det['focus']}", curses.color_pair(5))
            safe_addstr(stdscr, details_y_start + 2, 45, f"Kontext:  {det['ctx']} tokenu", curses.color_pair(5))
            
            # Treti radek detailu
            safe_addstr(stdscr, details_y_start + 3, 2, f"Vykon:    {det['tps']} TPS (NPU)", curses.color_pair(3) | curses.A_BOLD)
            safe_addstr(stdscr, details_y_start + 3, 45, f"Velikost: {det['size']}", curses.color_pair(7) | curses.A_BOLD)
            
            # Popis modelu (ctvrty a paty radek)
            safe_addstr(stdscr, details_y_start + 4, 2, f"Popis:", curses.color_pair(5) | curses.A_BOLD)
            safe_addstr(stdscr, details_y_start + 5, 2, f"{det['detail']}", curses.color_pair(5))

        # --- SEKCE 5: HTOP PATICKA ---
        footer = "F2/D Update  F3/X Delete  F5/R Refresh  F10/Q Quit"
        safe_addstr(stdscr, height - 1, 0, footer.ljust(width - 1), curses.A_REVERSE | curses.A_BOLD)

        stdscr.refresh()

        key = stdscr.getch()

        if key == -1:
            continue
            
        elif key in [curses.KEY_UP, ord('k'), ord('K')] and current_row > 0:
            current_row -= 1
        elif key in [curses.KEY_DOWN, ord('j'), ord('J')] and current_row < len(available) - 1:
            current_row += 1
            
        elif key in [ord('r'), ord('R'), curses.KEY_F5]:
            available = get_available_models()
            downloaded = get_downloaded_models()
            if current_row >= len(available): current_row = max(0, len(available) - 1)
            
        elif key in [ord('d'), ord('D'), 10, curses.KEY_F2]:
            if available:
                stdscr.timeout(-1) # Blokuj input behem stahovani
                action_download(stdscr, available[current_row], height, width)
                stdscr.timeout(1000) # Zpet na real-time polling
                downloaded = get_downloaded_models()
                
        elif key in [ord('x'), ord('X'), curses.KEY_F3, curses.KEY_DC]:
            if available and available[current_row] in downloaded:
                stdscr.timeout(-1)
                action_delete(stdscr, available[current_row], height, width)
                stdscr.timeout(1000)
                downloaded = get_downloaded_models()
                
        elif key in [ord('q'), ord('Q'), curses.KEY_F10]:
            break

def main():
    os.environ.setdefault('ESCDELAY', '25')
    curses.wrapper(tui_main)

if __name__ == '__main__':
    main()
