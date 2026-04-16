import os
import json
import math
import statistics
import urllib.parse
import re
import time
import feedparser
import concurrent.futures
from http_client import shared_session

# ================== 0. 状态机持久化 (Regime State Machine) ==================
STATE_FILE = "macro_state.json"

def load_state():
    """【LEVEL 9】加载深度记忆：包含仓位、真实净值(扣除滑点)、高水位线与宏观状态"""
    default_state = {
        "pos": {"VOO": 0.0, "QQQ": 0.0, "GOLD": 0.0, "COPX": 0.0},
        "risk_comp": 0.0,
        "nav_real": 1.0,      # 真实净值 (已扣除执行成本)
        "hwm": 1.0,           # 历史高水位
        "regime": "NORMAL"    # 宏观状态机
    }
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {**default_state, **data}
        except: pass
    return default_state

def save_state(state_dict):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state_dict, f)
    except: pass

# ================== 1. 底层网络与容错 ==================

def fetch_with_retry(url, is_json=False, max_retries=3):
    for i in range(max_retries):
        try:
            r = shared_session.get(url, timeout=10)
            if r.status_code == 200: return r.json() if is_json else r.text
        except Exception: time.sleep(2 ** i)
    return None

def fetch_html_with_fallback(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }
    try:
        r = shared_session.get(url, headers=headers, timeout=10)
        if r.status_code == 200 and "<title>Just a moment" not in r.text and "Cloudflare" not in r.text:
            return r.text
    except: pass

    try:
        r = shared_session.get(f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}", timeout=15)
        if r.status_code == 200:
            html = r.json().get("contents", "")
            if html and "<title>Just a moment" not in html: return html
    except: pass
    return None

def get_fred_history(series_id, api_key, limit=260, force_daily=False):
    if not api_key: return None, []
    freq = "&frequency=d" if force_daily else ""
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit={limit}{freq}"
    data = fetch_with_retry(url, is_json=True)
    hist = []
    if data and 'observations' in data:
        for item in data['observations']:
            val = item.get('value', '.')
            if val not in ['.', '', 'NaN', None]: hist.append(float(val))
    return (hist[0], hist) if hist else (None, [])

def get_yahoo_history(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2y"
    data = fetch_with_retry(url, is_json=True)
    try:
        closes = [c for c in data['chart']['result'][0]['indicators']['quote'][0]['close'] if c is not None]
        closes.reverse()
        return (closes[0], closes) if closes else (None, [])
    except: return None, []

def get_yahoo_quote(ticker):
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
    try:
        r = shared_session.get(url, timeout=5)
        if r.status_code == 200:
            res = r.json().get('quoteResponse', {}).get('result', [])
            if res: return res[0].get('regularMarketPrice')
    except: pass
    return None

# ================== 2. 专项数据抓取 ==================

def get_lme_spread():
    url = "https://www.westmetall.com/en/markdaten.php"
    html = fetch_html_with_fallback(url)
    if html:
        try:
            pattern = r'Copper\s*</a>.*?<a[^>]*>\s*([\d,\.]+)\s*</a>.*?<a[^>]*>\s*([\d,\.]+)\s*</a>'
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                cash = float(match.group(1).replace(',', ''))
                m3 = float(match.group(2).replace(',', ''))
                return f"${cash - m3:.2f}"
        except: pass
    return "盾/跳板全拦截"

def get_cips_structural_news():
    url = "https://news.google.com/rss/search?q=CIPS+%E4%BA%A4%E6%98%93+%E9%87%91%E9%A2%9D+OR+%E7%AC%94%E6%95%B0+when:1y&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        feed = feedparser.parse(url)
        if feed.entries:
            latest_news = feed.entries[0]
            title = latest_news.title.replace("|", "-")
            link = latest_news.link
            pub_date = latest_news.published if hasattr(latest_news, 'published') else "近期"
            highlight_title = re.sub(r'(\d+(?:\.\d+)?(?:万亿|亿|万))', r'**\1**', title)
            return f"<a href='{link}' target='_blank' style='color:#1a73e8; text-decoration:underline;'>{highlight_title}</a> <br><span style='font-size:11px;color:#888;'>({pub_date})</span>"
    except: pass
    return "系统未检索到本年度 CIPS 官方重磅数据"

def get_cnh_hibor():
    real_api_url = "https://www.bochk.com/whk/rates/cnyHiborRates/cnyHiborRates-enquiry.action?lang=cn"
    html = fetch_html_with_fallback(real_api_url)
    if html:
        try:
            on_match = re.search(r'(?:Overnight|隔夜)[^\d]*?([\d\.]+)\s*%?', html, re.IGNORECASE)
            if on_match: return float(on_match.group(1)), "隔夜(BOC)"
            w1_match = re.search(r'(?:1\s*Week|1星期|1周)[^\d]*?([\d\.]+)\s*%?', html, re.IGNORECASE)
            if w1_match: return float(w1_match.group(1)), "1周(BOC)"
        except: pass
    tickers = [("CNHON=X", "隔夜"), ("CNH1WD=X", "1周")]
    for ticker, name in tickers:
        val = get_yahoo_quote(ticker)
        if val is not None: return val, f"{name}(YQ)"
    for ticker, name in tickers:
        val, _ = get_yahoo_history(ticker)
        if val is not None: return val, f"{name}(YH)"
    return None, "全断流"

# ================== 3. 量化数学模型 ==================

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

def z_to_position(z):
    if z <= 0: return 0.0
    if z <= 1.0: return z * 0.3
    if z <= 2.0: return 0.3 + (z - 1.0) * 0.4
    if z <= 3.0: return 0.7 + (z - 2.0) * 0.3
    return 1.0

def get_ret(hist):
    if not hist or len(hist) < 2: return 0.0
    return (hist[0] - hist[1]) / hist[1]

def get_daily_change(history):
    if not history or len(history) < 2: return "0.00%"
    chg = get_ret(history) * 100
    color = "#d93025" if chg < 0 else ("#1e8e3e" if chg > 0 else "#555")
    sign = "+" if chg > 0 else ""
    return f"<span style='color:{color}; font-weight:bold;'>{sign}{chg:.2f}%</span>"

def pos_to_str(pos):
    pct = int(pos * 100)
    if pct == 0: return "0%"
    return f"{pct}%"

def fmt_val(val, suffix="", precision=2):
    if val is None: return "[无报价]"
    return f"{val:.{precision}f}{suffix}"

# ================== 4. 因子提取与量化计算 ==================

def extract_factors(api_key):
    f = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            "vix": executor.submit(get_yahoo_history, "^VIX"),
            "move": executor.submit(get_yahoo_history, "^MOVE"),
            "hy": executor.submit(get_fred_history, "BAMLH0A0HYM2", api_key),
            "rr": executor.submit(get_fred_history, "DFII10", api_key),
            "us10": executor.submit(get_fred_history, "DGS10", api_key),
            "dxy": executor.submit(get_yahoo_history, "DX-Y.NYB"),
            "rrp": executor.submit(get_fred_history, "RRPONTSYD", api_key, limit=300, force_daily=True),
            "t10": executor.submit(get_fred_history, "T10YIE", api_key),
            "yc": executor.submit(get_fred_history, "T10Y2Y", api_key),
            "hibor": executor.submit(get_cnh_hibor),
            "usd_cnh": executor.submit(get_yahoo_history, "USDCNH=X"),
            "usd_cny": executor.submit(get_yahoo_history, "USDCNY=X"),
            "lme": executor.submit(get_lme_spread),
            "walcl": executor.submit(get_fred_history, "WALCL", api_key, limit=300, force_daily=True),
            "tga": executor.submit(get_fred_history, "WTREGEN", api_key, limit=300, force_daily=True),
            "voo": executor.submit(get_yahoo_history, "VOO"),
            "qqq": executor.submit(get_yahoo_history, "QQQ"),
            "gold": executor.submit(get_yahoo_history, "GC=F"),
            "copx": executor.submit(get_yahoo_history, "COPX")
        }

        _, vix = futures["vix"].result()
        _, move = futures["move"].result()
        hy_cur, hy = futures["hy"].result()
        rr_cur, rr = futures["rr"].result()
        us10_cur, us10 = futures["us10"].result()
        dxy_cur, dxy = futures["dxy"].result()
        rrp_cur, rrp = futures["rrp"].result()
        t10_cur, t10 = futures["t10"].result()
        yc_cur, yc = futures["yc"].result()
        hibor_cur, hibor_name = futures["hibor"].result()

        usd_cnh_cur, _ = futures["usd_cnh"].result()
        usd_cny_cur, _ = futures["usd_cny"].result()
        lme_spread = futures["lme"].result()
        _, walcl = futures["walcl"].result()
        _, tga = futures["tga"].result()

        f['voo_cur'], f['voo_hist'] = futures["voo"].result()
        f['qqq_cur'], f['qqq_hist'] = futures["qqq"].result()
        f['gold_cur'], f['gold_hist'] = futures["gold"].result()
        f['copx_cur'], f['copx_hist'] = futures["copx"].result()

    if usd_cnh_cur is not None and usd_cny_cur is not None:
        cnh_stress_pips = (usd_cnh_cur - usd_cny_cur) * 10000
        spread_pips_str = f"{cnh_stress_pips:.0f} pips"
    else:
        cnh_stress_pips = 0.0
        spread_pips_str = "无报价"

    f['raw'] = {
        'hy': hy_cur, 'rr': rr_cur, 'us10': us10_cur, 'dxy': dxy_cur,
        'rrp': rrp_cur, 't10': t10_cur, 'yc': yc_cur,
        'hibor': hibor_cur, 'hibor_name': hibor_name,
        'lme_spread': lme_spread,
        'usd_cnh': usd_cnh_cur, 'usd_cny': usd_cny_cur,
        'cnh_cny_spread': spread_pips_str
    }
    f['cnh_stress_pips'] = cnh_stress_pips

    f['z_vix'] = calc_robust_z(vix[0], vix) if vix else 0.0
    f['z_move'] = calc_robust_z(move[0], move) if move else 0.0
    f['z_hy'] = calc_robust_z(hy[0], hy) if hy else 0.0
    f['z_realrate'] = calc_robust_z(rr[0], rr) if rr else 0.0
    f['z_us10y'] = calc_robust_z(us10[0], us10) if us10 else 0.0
    f['z_dxy'] = calc_robust_z(dxy[0], dxy) if dxy else 0.0

    f['z_yc'] = calc_robust_z(yc_cur, yc) if yc else 0.0
    f['z_t10'] = calc_robust_z(t10_cur, t10) if t10 else 0.0

    f['z_vix_mom'] = calc_momentum_z(vix, window=5)
    f['z_realrate_mom'] = calc_momentum_z(rr, window=3)

    f['liq_delta_z'] = 0.0
    f['liq_impulse'] = 0.0
    if walcl and rrp and tga:
        min_len = min(len(walcl), len(rrp), len(tga))
        if min_len > 30:
            raw_deltas = []
            for i in range(min_len - 20):
                l_cur = walcl[i] - rrp[i] - tga[i]
                l_past = walcl[i+20] - rrp[i+20] - tga[i+20]
                raw_deltas.append(l_cur - l_past)
            smoothed = calc_ema(raw_deltas, span=10)
            f['liq_delta_z'] = calc_robust_z(smoothed[0], smoothed) if smoothed else 0.0
            liq_mom_z = calc_momentum_z(smoothed, window=5) if smoothed else 0.0
            f['liq_impulse'] = f['liq_delta_z'] + 0.5 * liq_mom_z

    return f

def calculate_quant_execution(f):
    pos, const, action = {}, {}, {}

    # ================== 【LEVEL 9: 真实执行反馈 (Real PnL Feedback)】 ==================
    state = load_state()
    prev_pos = state.get("pos", {"VOO": 0.0, "QQQ": 0.0, "GOLD": 0.0, "COPX": 0.0})

    # 1. 计算理论涨跌与真实换手摩擦成本 (Slippage & Spread = ~15 bps per turnover)
    port_ret = 0.0
    port_ret += prev_pos.get("VOO", 0) * get_ret(f.get('voo_hist'))
    port_ret += prev_pos.get("QQQ", 0) * get_ret(f.get('qqq_hist'))
    port_ret += prev_pos.get("GOLD", 0) * get_ret(f.get('gold_hist'))
    port_ret += prev_pos.get("COPX", 0) * get_ret(f.get('copx_hist'))

    # 假设每次状态转换的过往 turnover 已扣除。由于是单日结算，用静态滞后模拟。
    nav_real = state.get("nav_real", 1.0) * (1 + port_ret)
    hwm = max(state.get("hwm", 1.0), nav_real)
    drawdown = (hwm - nav_real) / hwm if hwm > 0 else 0.0

    # ================== 【LEVEL 9: 未知风险极端惩罚 (Tail Proxy)】 ==================
    risk_comp_base = max(f['z_vix'], f['z_move'], f['z_hy']) * 0.6 + sum([f['z_vix'], f['z_move'], f['z_hy']])/3.0 * 0.4
    risk_comp_adj = risk_comp_base + 0.5 * max(0, f.get('z_vix_mom', 0.0))

    # 未知黑天鹅代理：VIX与MOVE同时出现极端变异加速度
    tail_shock_proxy = max(0, f.get('z_vix_mom', 0.0) + f.get('z_move', 0.0))

    # 四相宏观状态机判定
    if risk_comp_adj > 2.5 or tail_shock_proxy > 4.0: current_regime = "CRISIS"
    elif drawdown > 0.05: current_regime = "DRAWDOWN"
    elif risk_comp_adj < 0.8 and drawdown < 0.02: current_regime = "RISK_ON"
    else: current_regime = "NORMAL"

    def risk_penalty(r):
        if r < 1.0: return r * 0.3
        elif r < 2.0: return r * 0.8
        else: return r * 1.5

    def rate_penalty(z):
        if z < 0: return z * 0.5
        elif z < 1.5: return z * 1.0
        else: return z * 2.0

    # ================== 【LEVEL 9: 动态非平稳权重 (Regime Dynamic Weights)】 ==================
    if current_regime == "CRISIS":
        w_liq, w_risk, w_rate = 0.1, 2.0, 1.0 # 危机中无视放水，只看风险
    elif current_regime == "DRAWDOWN":
        w_liq, w_risk, w_rate = 0.4, 1.2, 0.8 # 回撤期趋于保守
    else:
        w_liq, w_risk, w_rate = (0.3, 1.2, 0.8) if f['z_us10y'] > 1.5 else (0.8, 0.8, 0.4)

    usd_tightening = max(0, f['z_dxy'])
    global_liq = f['liq_impulse'] - 0.2 * usd_tightening
    z_growth = -f['z_yc']

    z_voo = (global_liq * w_liq) - (risk_penalty(risk_comp_adj) * w_risk) - (rate_penalty(f['z_realrate']) * 1.2)
    z_qqq = (global_liq * w_liq * 1.5) - (risk_penalty(risk_comp_adj) * w_risk * 1.2) - (rate_penalty(f['z_realrate']) * 1.5)

    gold_penalty = rate_penalty(f['z_realrate']) + 0.5 * max(0, f.get('z_realrate_mom', 0.0))
    z_gold = (-gold_penalty * 1.0 - f['z_dxy'] * 0.5 + f['z_t10'] * 0.8 + risk_penalty(risk_comp_adj) * 0.3)
    cnh_stress = max(0, f.get('cnh_stress_pips', 0) / 300.0)
    z_copx = -(f['z_dxy'] * 0.6) + (global_liq * w_liq) - (risk_penalty(risk_comp_adj) * w_risk) - cnh_stress + (z_growth * 0.5)

    def apply_filters(price, history, base_z, vol_z_override):
        if not history or len(history) < 210: return 0.0, "数据不足"
        ma200 = calc_ma(history, 200)
        slope = calc_ma_slope(history, 50, 10)

        # 【LEVEL 9: 不确定性概率折扣 (Confidence Multiplier)】
        confidence = 1.0 / (1.0 + max(0, vol_z_override - 1.0) * 0.3)

        target = z_to_position(base_z) * confidence # 乘以不确定性折扣
        msgs = []
        if vol_z_override > 1.5: msgs.append(f"高波动折扣(x{confidence:.2f})")

        if price < ma200 and slope < 0: return 0.0, "🚨 破位向下"
        elif price >= ma200 and slope < 0: target = min(target, 0.3); msgs.append("⚠️ 均线背离")
        elif price < ma200 and slope > 0: target = min(target, 0.3); msgs.append("⚠️ 熊市反弹")
        elif price >= ma200 and slope > 0: target = min(target + 0.3, 1.0); msgs.append("🚀 趋势确认")

        return target, " | ".join(msgs) if msgs else "✅ 结构健康"

    # 提取各自资产自身的历史波动率，计算概率自信度
    target_pos = {}
    vol_voo = calc_volatility_z(f.get('voo_hist', []), 20)
    vol_qqq = calc_volatility_z(f.get('qqq_hist', []), 20)
    vol_gold = calc_volatility_z(f.get('gold_hist', []), 20)
    vol_copx = calc_volatility_z(f.get('copx_hist', []), 20)

    target_pos["VOO"], const["VOO"] = apply_filters(f['voo_cur'], f['voo_hist'], z_voo, vol_voo)
    target_pos["QQQ"], const["QQQ"] = apply_filters(f['qqq_cur'], f['qqq_hist'], z_qqq, vol_qqq)
    target_pos["GOLD"], const["GOLD"] = apply_filters(f['gold_cur'], f['gold_hist'], z_gold, vol_gold)
    target_pos["COPX"], const["COPX"] = apply_filters(f['copx_cur'], f['copx_hist'], z_copx, vol_copx)

    # ================== 风险预算与归因 ==================
    limit_corr = 1.0
    limit_budget = 1.0
    limit_tail = 1.0

    corr_voo_qqq = calc_correlation(f.get('voo_hist', []), f.get('qqq_hist', []), window=60)
    def corr_penalty_func(c):
        if c < 0.7: return 1.0
        elif c < 0.85: return 1.2
        elif c < 0.9: return 1.4
        else: return 1.7
    effective_qqq = target_pos["QQQ"] * corr_penalty_func(corr_voo_qqq)
    total_exposure = target_pos["VOO"] + effective_qqq + target_pos["COPX"]
    if total_exposure > 2.0:
        limit_corr = 2.0 / total_exposure
        const["PORTFOLIO"] = f"⚖️ 高度相关(ρ={corr_voo_qqq:.2f})挤压敞口"

    f['risk_exposure'] = {
        "rate": target_pos["QQQ"] * 1.5 + target_pos["VOO"] * 0.8 + target_pos["GOLD"] * 1.0,
        "liquidity": target_pos["VOO"] * 1.0 + target_pos["QQQ"] * 1.5 + target_pos["COPX"] * 1.0,
        "china_macro": target_pos["COPX"] * 1.5
    }

    dd_penalty = max(0.5, 1.0 - drawdown * 4.0)
    RISK_BUDGET = {
        "rate": 1.5 * dd_penalty,
        "liquidity": 2.0 * dd_penalty,
        "china_macro": 1.0 * dd_penalty
    }

    triggered_budgets = []
    for k in RISK_BUDGET:
        if f['risk_exposure'][k] > RISK_BUDGET[k]:
            overload = f['risk_exposure'][k] / RISK_BUDGET[k]
            if (1.0 / overload) < limit_budget: limit_budget = 1.0 / overload
            triggered_budgets.append(k)

    if triggered_budgets:
        budget_names = ",".join(triggered_budgets)
        msg = f"🛡️ 触发[{budget_names}]极值预算控制"
        const["PORTFOLIO"] = msg if "PORTFOLIO" not in const else const["PORTFOLIO"] + f" | {msg}"

    if tail_shock_proxy > 4.0:
        limit_tail = 0.5 # 黑天鹅极值无条件惩罚
        const["GLOBAL"] = "🌪️ 侦测到未知极端宏观尾部，触发强制降维"
    elif risk_comp_adj > 2.5:
        limit_tail = 0.3
        const["GLOBAL"] = "🔥 已知系统性极度恐慌：全线强制降至 30% 防深 V"

    final_scale = min(limit_corr, limit_budget, limit_tail)
    for k in ["VOO", "QQQ", "GOLD", "COPX"]:
        target_pos[k] *= final_scale

    # ================== 真实执行与换手率核算 ==================
    daily_turnover = 0.0
    for asset in ["VOO", "QQQ", "GOLD", "COPX"]:
        target = target_pos[asset]
        prev = prev_pos.get(asset, 0.0)

        if target == 0.0:
            pos[asset] = 0.0
            action[asset] = "🛑 止损清仓 (Clear)"
        else:
            alpha = 0.5 if target < prev else 0.2
            if current_regime == "CRISIS" and target < prev: alpha = 0.8

            actual_pos = prev + (target - prev) * alpha
            pos[asset] = actual_pos

            if abs(actual_pos - prev) < 0.02: action[asset] = "🔒 平滑微调 (Smooth)"
            elif actual_pos > prev: action[asset] = "🟢 顺势加仓 (Scale In)"
            else: action[asset] = "🔻 减持防守 (Scale Out)"

        daily_turnover += abs(pos[asset] - prev)

    # 【LEVEL 9核心】扣除换手摩擦 (15 bps/单边 turnover)，更新真实净值
    friction_cost = daily_turnover * 0.0015
    nav_real = nav_real - friction_cost

    new_state = {
        "pos": pos,
        "risk_comp": risk_comp_adj,
        "nav_real": nav_real,
        "hwm": hwm,
        "regime": current_regime
    }
    save_state(new_state)

    f['system_nav'] = nav_real
    f['system_dd'] = drawdown
    f['system_regime'] = current_regime
    f['dd_penalty'] = dd_penalty
    f['daily_turnover'] = daily_turnover
    f['friction_cost'] = friction_cost

    return pos, action, risk_comp_adj, const, f

# ================== 5. 动态解读引擎与面板 ==================

def generate_dynamic_analysis(raw, raw_f, risk_comp):
    desc = {}
    lme_str = raw.get('lme_spread', '')
    if '$' in lme_str:
        try:
            val = float(lme_str.replace('$', ''))
            desc['A'] = "🔥 现货升水：实体极度缺货，存在逼空动能。" if val > 0 else "🧊 期货升水：目前库存充裕，结构健康。"
        except: desc['A'] = "⚠️ 暂无最新结构数据"
    else: desc['A'] = "⚠️ 暂无最新结构数据"

    lz = raw_f.get('liq_delta_z', 0)
    if lz > 1.0: desc['B'] = "🌊 放水周期：流动性边际大幅宽松，利好风险资产。"
    elif lz < -1.0: desc['B'] = "🏜️ 抽水周期：流动性边际收紧，压制估值。"
    else: desc['B'] = "⚖️ 中性震荡：流动性无明显边际方向。"

    pips_str = str(raw.get('cnh_cny_spread', ''))
    if 'pips' in pips_str:
        try:
            pips = int(pips_str.split()[0])
            if pips > 300: desc['C'] = "🚨 极度危险：外资在离岸大肆做空人民币，港股承压。"
            elif pips < -200: desc['C'] = "🔥 逼空：离岸大幅升值，央行或在抽水打爆空头。"
            else: desc['C'] = "✅ 情绪平稳：内外资预期一致，无显著单边资金。"
        except: desc['C'] = "⚠️ 暂无有效价差"
    else: desc['C'] = "⚠️ 暂无有效价差"

    t10 = raw.get('t10')
    if t10 is not None:
        if t10 > 2.5: desc['D'] = "🔥 预期高涨：通胀重燃风险，利好抗通胀资产。"
        elif t10 < 2.0: desc['D'] = "🧊 预期降温：需求衰退担忧进一步升温。"
        else: desc['D'] = "⚖️ 预期温和：通胀预期处于常态区间。"
    else: desc['D'] = "⚠️ 场内数据缺失"

    rz = raw_f.get('z_realrate', 0)
    if rz > 1.5: desc['E'] = "🧱 极度压制：实际利率达历史高位，黄金估值承压。"
    elif rz < -1.5: desc['E'] = "🚀 极度宽松：实际利率大跌，黄金的绝佳顺风期。"
    else: desc['E'] = "⚖️ 估值中性：利率未见极端偏离。"

    hy = raw.get('hy')
    hz = raw_f.get('z_hy', 0)
    if hy is not None and (hy > 5.0 or hz > 2.0): desc['F'] = "🚨 违约警报：企业融资困难，经济衰退风险飙升！"
    else: desc['F'] = "✅ 信用健康：高收益债市未见违约恐慌。"

    yc = raw.get('yc')
    if yc is not None:
        if yc < -0.1: desc['G'] = "⚠️ 深度倒挂：长周期经济衰退正在酝酿。"
        elif -0.1 <= yc <= 0.2: desc['G'] = "🚨 倒挂解除中：历史规律显示此时极易兑现崩盘！"
        else: desc['G'] = "✅ 曲线正常：经济周期处于健康扩展期。"
    else: desc['G'] = "⚠️ 场内数据缺失"

    dz = raw_f.get('z_dxy', 0)
    if dz > 1.5: desc['H'] = "🌪️ 强势美元：全球流动性被虹吸，重挫非美与大宗。"
    elif dz < -1.5: desc['H'] = "🌊 弱势美元：资金流出美国，利好新兴市场。"
    else: desc['H'] = "⚖️ 震荡区间：未形成单边的极值趋势。"

    rc = risk_comp
    if rc > 2.0: desc['I'] = "🔥 极度恐慌：系统性崩盘特征，强制切入防御避险模式！"
    elif rc > 1.0: desc['I'] = "⚠️ 风险升温：市场情绪脆弱，系统已自动限制多头敞口。"
    else: desc['I'] = "✅ 情绪稳定：市场结构健康，可放心顺势交易。"

    hibor = raw.get('hibor')
    if hibor is not None:
        if hibor > 4.5: desc['J'] = "🚨 离岸抽水：拆借利率飙升，做空人民币成本急剧增加！"
        else: desc['J'] = "✅ 流动性充裕：离岸资金面健康平稳。"
    else: desc['J'] = "⚠️ 场外数据未正常推送"

    return desc

def format_cell(dynamic_text, static_text):
    return f"{dynamic_text}<br><span style='font-size:11px; font-style:italic; color:#666;'>({static_text})</span>"

def fetch_macro_indicators(fred_api_key=None):
    """
    ========================================================================
    【核心架构文档：A-J 项目及 CIPS 绝对数值与 Z-Score 因子计算逻辑】
    ========================================================================
    A. LME铜升贴水:
       - 绝对值: 爬虫解析 www.westmetall.com (Copper Cash 减去 3-months)。
       - 因子状态(Z-Score): 无。用作物理微观印证。
    B. 逆回购(RRP) / 净流动性:
       - 绝对值: FRED API 提取 `RRPONTSYD` (美联储隔夜逆回购绝对规模)。
       - 因子状态(Z-Score): 提取过去 1 年的 WALCL(总资产) - RRP - TGA 计算出净流动性，求其 20 日变化量(Delta)的 EMA 平滑序列，最终对该序列求 Robust Z-Score。
    C. 核心实时汇率:
       - 绝对值: Yahoo API 获取 `USDCNY=X`(在岸), `USDCNH=X`(离岸), `HKDCNY=X`(港币兑人民币)。
       - 因子状态(价差 pips): (离岸 - 在岸) * 10000。无 Z-Score。
    D. 盈亏通胀率:
       - 绝对值: FRED API 提取 `T10YIE` (10年期盈亏平衡通胀率)。
       - 因子状态(Z-Score): 无。
    E. 实际利率(TIPS):
       - 绝对值: FRED API 提取 `DFII10` (10年期通胀保值债券收益率)。
       - 因子状态(Z-Score): 基于过去 1 年历史数据的 Robust Z-Score (横截面绝对值度量) + 3日动量的一阶导数度量(加速度)。
    F. 高收益债利差:
       - 绝对值: FRED API 提取 `BAMLH0A0HYM2` (美国高收益企业债期权调整利差)。
       - 因子状态(Z-Score): 基于过去 1 年历史数据的 Robust Z-Score。
    G. 长短端利差:
       - 绝对值: FRED API 提取 `T10Y2Y` (10年期国债收益率 减去 2年期国债收益率)。
       - 因子状态(Z-Score): 无。用于定性判断周期拐点。
    H. 美元指数(DXY):
       - 绝对值: Yahoo API 提取 `DX-Y.NYB`。
       - 因子状态(Z-Score): 基于过去 1 年历史数据的 Robust Z-Score。
    I. 复合风险指数:
       - 绝对值: 综合衍生计算，无单一原始数据。
       - 因子状态(Z-Score): `0.6 * Max(VIX_Z, MOVE_Z, HY_Z) + 0.4 * Mean(VIX_Z, MOVE_Z, HY_Z)`。兼顾黑天鹅极值与系统性厚度。
    J. 跨境流动性(HIBOR):
       - 绝对值: 穿透抓取中银香港(BOCHK)底层接口，或雅虎 API `CNHON=X` 等多期限备用。
       - 因子状态(Z-Score): 无。
    CIPS 结构面新闻:
       - 绝对值: 抓取 Google News RSS "CIPS 交易 金额 OR 笔数" (回溯1年)，并转为 Markdown 锚点链接。
       - 因子状态(Z-Score): 无。长线定性跟踪。
    ========================================================================
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_f = executor.submit(extract_factors, fred_api_key)
        future_cips = executor.submit(get_cips_structural_news)

        f = future_f.result()
        cips_news = future_cips.result()

    pos, action, risk_comp, constraints, raw_f = calculate_quant_execution(f)
    raw = f['raw']
    risk_exp = raw_f.get('risk_exposure', {})

    hibor_name = raw.get('hibor_name', '隔夜')
    desc = generate_dynamic_analysis(raw, raw_f, risk_comp)

    md = "## 🗺️ 市场宽度与全景热力图 (Market Breadth)\n\n"
    md += "> 提示：Finviz 底层为防爬虫实时渲染，点击下方加密通道直达原生热力图：\n\n"
    md += "👉 **[点击查看：美股 标普500 热力图 (S&P 500)](https://finviz.com/map.ashx?t=sec)**\n\n"
    md += "👉 **[点击查看：全球核心资产 热力图 (World)](https://finviz.com/map.ashx?t=geo)**\n\n"
    md += "---\n\n"

    regime_emoji = {"RISK_ON": "🚀 狂暴多头", "NORMAL": "⚖️ 常态震荡", "DRAWDOWN": "🛡️ 回撤逆风期", "CRISIS": "🚨 宏观危机"}
    md += "## 🧭 桥水级：动态风险操作系统 (Risk OS - Level 9)\n\n"
    md += "| 真实净值(NAV) | 当前回撤 | 今日执行摩擦成本 | 宏观状态机(Regime) | 动态风险预算乘数 |\n"
    md += "| :--- | :--- | :--- | :--- | :--- |\n"
    md += f"| **{raw_f['system_nav']:.4f}** | **{raw_f['system_dd']*100:.2f}%** | **-{raw_f['friction_cost']*10000:.1f} bps** | **{regime_emoji.get(raw_f['system_regime'], '未知')}** | **{raw_f['dd_penalty']:.2f}x** |\n\n"

    md += "| 宏观风险维度 (Risk Dimension) | 系统当前暴露量 | 设定预算上限 (Budget) | 风险诊断状态 |\n"
    md += "| :--- | :--- | :--- | :--- |\n"

    r_rate = risk_exp.get('rate', 0)
    r_budget = 1.5 * raw_f['dd_penalty']
    r_state = "🔴 超出预算 (限制压降中)" if r_rate > r_budget else ("🟡 逼近红线" if r_rate > r_budget*0.8 else "🟢 安全余量充足")
    md += f"| **利率杀估值风险 (Rate Risk)** | **{r_rate:.2f}** | {r_budget:.2f} | {r_state} |\n"

    l_rate = risk_exp.get('liquidity', 0)
    l_budget = 2.0 * raw_f['dd_penalty']
    l_state = "🔴 超出预算 (限制压降中)" if l_rate > l_budget else ("🟡 逼近红线" if l_rate > l_budget*0.8 else "🟢 安全余量充足")
    md += f"| **全球流动性枯竭 (Liquidity Risk)** | **{l_rate:.2f}** | {l_budget:.2f} | {l_state} |\n"

    c_rate = risk_exp.get('china_macro', 0)
    c_budget = 1.0 * raw_f['dd_penalty']
    c_state = "🔴 超出预算 (限制压降中)" if c_rate > c_budget else "🟢 安全余量充足"
    md += f"| **中国/新兴市场衰退 (China Macro)** | **{c_rate:.2f}** | {c_budget:.2f} | {c_state} |\n\n"
    md += "---\n\n"

    md += "## 🤖 资产策略控制台 (Signal → Execution 闭环)\n\n"
    if "GLOBAL" in constraints: md += f"> **🚨 尾部熔断**：{constraints['GLOBAL']}\n\n"
    if "PORTFOLIO" in constraints: md += f"> **⚖️ 组合风控**：{constraints['PORTFOLIO']}\n\n"

    md += "| 资产大类 | 今日涨跌幅 | EMA 平滑后仓位 | 💡 操作建议 (Action) | 状态引擎 (Regime) |\n"
    md += "| :--- | :--- | :--- | :--- | :--- |\n"
    md += f"| **标普500 (VOO)** | {get_daily_change(f['voo_hist'])} | **{pos_to_str(pos['VOO'])}** | **{action['VOO']}** | {constraints['VOO']} |\n"
    md += f"| **纳指100 (QQQ)** | {get_daily_change(f['qqq_hist'])} | **{pos_to_str(pos['QQQ'])}** | **{action['QQQ']}** | {constraints['QQQ']} |\n"
    md += f"| **避险黄金 (18.HK)** | {get_daily_change(f['gold_hist'])} | **{pos_to_str(pos['GOLD'])}** | **{action['GOLD']}** | {constraints['GOLD']} |\n"
    md += f"| **大宗商品 (COPX)** | {get_daily_change(f['copx_hist'])} | **{pos_to_str(pos['COPX'])}** | **{action['COPX']}** | {constraints['COPX']} |\n\n"

    md += "## 📈 核心宏观全景面板 (指标判读分析)\n\n"
    md += "| 变量名称 | 最新绝对数值 | 因子状态 (Z-Score) | 核心驱动逻辑 (今日动态判读) |\n"
    md += "| :--- | :--- | :--- | :--- |\n"

    md += f"| **A. LME铜升贴水** | **{raw['lme_spread']}** | 物理逼空 | {format_cell(desc['A'], '现货贵于期货(>0)说明实体库存极缺')} |\n"
    md += f"| **B. 逆回购(RRP)** | **{fmt_val(raw['rrp'], ' B', 1)}** | **{fmt_val(raw_f['liq_impulse'])}** (流动脉冲) | {format_cell(desc['B'], '水库释放器，连同TGA构成美元总水位')} |\n"

    fx_str = f"在岸(CNY): **{fmt_val(raw['usd_cny'], precision=4)}**<br>离岸(CNH): **{fmt_val(raw['usd_cnh'], precision=4)}**<br>港币兑RMB: **{fmt_val(raw['hkd_cny'], precision=4)}**"
    md += f"| **C. 核心实时汇率** | {fx_str} | 价差: **{raw['cnh_cny_spread']}** | {format_cell(desc['C'], '价差剧烈扩大(>300)意味外资正在做空中国资产')} |\n"

    md += f"| **D. 盈亏通胀率** | **{fmt_val(raw['t10'], '%')}** | 远期定价 | {format_cell(desc['D'], '黄金的助推剂，突破前高需重仓')} |\n"

    md += f"| **E. 实际利率(TIPS)**| **{fmt_val(raw['rr'], '%')}** <span style='font-size:11px;color:#888;'>(T-1, FRED)</span> | **{fmt_val(raw_f['z_realrate'])}** | {format_cell(desc['E'], '黄金绝对反向锚，极高位时压制一切估值')} |\n"

    md += f"| **F. 高收益债利差** | **{fmt_val(raw['hy'], '%')}** | **{fmt_val(raw_f['z_hy'])}** (信用) | {format_cell(desc['F'], '企业违约生死线，破 5% 亮红灯')} |\n"
    md += f"| **G. 长短端利差** | **{fmt_val(raw['yc'], '%')}** | 周期警报 | {format_cell(desc['G'], '10Y-2Y 倒挂解除瞬间，通常衰退正式兑现')} |\n"
    md += f"| **H. 美元指数(DXY)** | **{fmt_val(raw['dxy'])}** | **{fmt_val(raw_f['z_dxy'])}** | {format_cell(desc['H'], '全球流动性虹吸指标，走强利空大宗')} |\n"
    md += f"| **I. 复合风险指数** | 综合测算 | **{fmt_val(risk_comp)}** | {format_cell(desc['I'], '结合 VIX, MOVE, HY。>1.5严禁逆势重仓')} |\n"
    md += f"| **J. 跨境流动性(HIBOR)**| **{fmt_val(raw['hibor'], '%')}** ({hibor_name}) | 离岸人民币 | {format_cell(desc['J'], 'CNH 隔夜拆借利率暴涨说明离岸系统遭抽水')} |\n"
    md += f"| ↳ *CIPS 结构面新闻* | **最新快报** | <span style='color:#555;'>{cips_news}</span> | <span style='font-size:11px; font-style:italic; color:#666;'>(长线低频跟踪，反映人民币国际化实质进度)</span> |\n"

    return md + "\n---\n"
