import math
import statistics

def calc_robust_z(current, history):
    if not history or len(history) < 20: return 0.0
    med = statistics.median(history)
    mad = statistics.median([abs(x - med) for x in history])
    adjusted_mad = mad * 1.4826
    return (current - med) / adjusted_mad if adjusted_mad != 0 else 0.0

def calc_ma(history, periods):
    return sum(history[:periods]) / periods if history and len(history) >= periods else None

def calc_ma_slope(history, ma_period=50, lookback=10):
    if not history or len(history) < ma_period + lookback: return 0.0
    ma_today = calc_ma(history[:ma_period], ma_period)
    ma_past = calc_ma(history[lookback:lookback+ma_period], ma_period)
    return (ma_today - ma_past) / ma_past if ma_past else 0.0

def calc_volatility_z(history, window=20):
    if not history or len(history) < window + 260: return 0.0
    vol_hist = []
    for i in range(len(history) - window):
        slice_p = history[i:i+window+1]
        rets = [(slice_p[j] - slice_p[j+1])/slice_p[j+1] for j in range(window)]
        var = sum((r - sum(rets)/window)**2 for r in rets) / (window - 1)
        vol_hist.append(math.sqrt(var) * math.sqrt(252))
    return calc_robust_z(vol_hist[0], vol_hist)

def calc_momentum_z(history, window=3):
    if not history or len(history) < window + 20: return 0.0
    momentum_series = [history[i] - history[i+window] for i in range(len(history)-window)]
    return calc_robust_z(momentum_series[0], momentum_series)

def calc_correlation(x, y, window=60):
    if not x or not y: return 0.0
    min_len = min(len(x), len(y), window)
    if min_len < 20: return 0.0
    slice_x, slice_y = x[:min_len], y[:min_len]
    mean_x, mean_y = sum(slice_x)/min_len, sum(slice_y)/min_len
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(slice_x, slice_y))
    var_x = sum((a - mean_x)**2 for a in slice_x)
    var_y = sum((b - mean_y)**2 for b in slice_y)
    if var_x < 1e-8 or var_y < 1e-8: return 0.0
    return cov / math.sqrt(var_x * var_y)

def calc_ema(history, span=10):
    if not history: return []
    rev_hist = list(reversed(history))
    ema = [rev_hist[0]]
    alpha = 2.0 / (span + 1.0)
    for i in range(1, len(rev_hist)):
        ema.append(rev_hist[i] * alpha + ema[-1] * (1.0 - alpha))
    ema.reverse()
    return ema

def get_ret(hist):
    if not hist or len(hist) < 2: return 0.0
    return (hist[0] - hist[1]) / hist[1]
