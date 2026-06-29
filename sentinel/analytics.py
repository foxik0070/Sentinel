import numpy as np
from . import state, config

# ==============================================================================
# CONFIGURATION & THRESHOLDS — override via config.yaml analytics section
# ==============================================================================
MIN_ABS_DELTA = 100.0
MIN_PCT_DELTA = 0.40
MIN_R_SQUARED = 0.90

def _cfg(key, default):
    return getattr(config, 'ANALYTICS', {}).get(key, default)

def CRITICAL_TTC_HOURS(): return _cfg('critical_ttc_hours', 24)
def WARNING_TTC_HOURS():  return _cfg('warning_ttc_hours', 72)

CAT_FILESYSTEM = "FS"
CAT_SENSOR = "HW"
CAT_SYSTEM = "SYSTEM"

def smooth_data(data, window_size=3):
    """Vyhlazení dat klouzavým průměrem pro odstranění šumu."""
    if len(data) < window_size:
        return data
    kernel = np.ones(window_size) / window_size
    return np.convolve(data, kernel, mode='valid')

def is_noise(current, history):
    """Rozpozná, zda jde o pouhý šum u malých čísel."""
    avg = np.mean(history)
    std = np.std(history)
    
    if std < 0.5: return True
    if abs(avg) < 500 and abs(current - avg) < 20:
        return True
        
    return False

def calculate_mann_kendall(data):
    """Zjednodušený Mann-Kendall test trendu."""
    n = len(data)
    if n < 4: return 0.0
    score = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            score += np.sign(data[j] - data[i])
    max_score = (n * (n - 1)) / 2
    return score / max_score if max_score != 0 else 0

def predict_time_to_threshold(current_val, slope, threshold, points_per_hour=12):
    if slope == 0: return float('inf')
    steps_needed = (threshold - current_val) / slope
    if steps_needed < 0: return float('inf')
    return steps_needed / points_per_hour

def check_seasonality(current_val, history):
    if len(history) < 288: return False, None
    yesterday_avg = np.mean(history[0:3])
    if yesterday_avg == 0: return False, None
    deviation = abs(current_val - yesterday_avg) / abs(yesterday_avg)
    if deviation < 0.15:
        return True, f"Kopíruje včerejšek ({yesterday_avg:.1f})"
    return False, None

def analyze_trend(metric_name, current_val, category):
    history = state.get_metric_history(metric_name, limit=288)
    if len(history) < 12: return "OK", None

    recent_history = history[-12:]
    smoothed_history = smooth_data(recent_history, window_size=3)
    
    avg_long = np.mean(history)
    
    if is_noise(current_val, recent_history):
        return "OK", None

    # LINEAR REGRESSION CHECK
    x = np.arange(len(smoothed_history))
    slope, intercept = np.polyfit(x, smoothed_history, 1)
    
    y_pred = slope * x + intercept
    ss_res = np.sum((smoothed_history - y_pred) ** 2)
    ss_tot = np.sum((smoothed_history - np.mean(smoothed_history)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
    
    change_per_hour = slope * 12 
    current_pct_trend = abs(change_per_hour) / abs(avg_long) if avg_long != 0 else 0

    # 1. FILESYSTEM (Disk usage)
    if category == CAT_FILESYSTEM or "disk" in metric_name.lower():
        if r_squared > MIN_R_SQUARED:
            target_limit = 100.0 
            if "free" in metric_name.lower(): target_limit = 0.0
            
            hours_left = predict_time_to_threshold(current_val, slope, target_limit)
            
            if hours_left < CRITICAL_TTC_HOURS():
                return "CRITICAL", f"⚠️ KRITICKÉ: Disk bude plný za {hours_left:.1f}h! (Trend: {int(change_per_hour)}/h)"
            if hours_left < WARNING_TTC_HOURS():
                return "WARNING", f"Varování: Disk bude plný za {hours_left/24:.1f} dní."
            
            if abs(change_per_hour) > MIN_ABS_DELTA:
                 return "PREDICTION", f"Disk capacity changing: {int(change_per_hour)}/h (R²={r_squared:.2f})"

    # 2. SENSORS (Teplota, RPM, Power, HPC)
    if category == CAT_SENSOR or "temp" in metric_name.lower() or "power" in metric_name.lower() or "gpu" in category.lower():
        is_seasonal, _ = check_seasonality(current_val, history)
        if is_seasonal: return "OK", None

        if r_squared > MIN_R_SQUARED:
            if abs(change_per_hour) > MIN_ABS_DELTA and current_pct_trend > MIN_PCT_DELTA:
                return "WARNING", f"Trend detected (R²={r_squared:.2f}, {int(change_per_hour)}/h)"

    # 3. SYSTEM (Generic)
    std_dev_long = np.std(history)
    if std_dev_long > 0:
        z_score = (current_val - avg_long) / std_dev_long
        if abs(z_score) > 4.0:
             is_seasonal, _ = check_seasonality(current_val, history)
             if not is_seasonal and abs(current_val - avg_long) > MIN_ABS_DELTA:
                return "WARNING", f"Anomálie: Hodnota mimo normál (Z-Score: {z_score:.1f})"

    return "OK", None
