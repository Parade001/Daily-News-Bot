import math
import statistics
import urllib.parse
import re
import time
import feedparser
import concurrent.futures
from http_client import shared_session

# ================== 1. 底层网络与容错 ==================

def fetch_with_retry(url, is_json=False, max_retries=3):
    for i in range(max_retries):
        try:
            r = shared_session.get(url, timeout=10)
            if r.status_code == 200:
                return r.json() if is_json else r.text
        except:
            time.sleep(2 ** i)
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
            if html and "<title>Just a moment" not in html:
                return html
    except: pass

    try:
        r = shared_session.get(f"https://api.codetabs.com/v1/proxy/?quest={url}", timeout=15)
        if r.status_code == 200 and "<title>Just a moment" not in r.text:
            return r.text
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
    """【备用黑魔法】调用雅虎瞬时报价前端 API，无视历史 K 线断流"""
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
    try:
        r = shared_session.get(url, timeout=5)
        if r.status_code == 200:
            res = r.json().get('quoteResponse', {}).get('result', [])
            if res:
                return res[0].get('regularMarketPrice')
    except: pass
    return None

# ================== 2. 专项数据抓取 (LME / CIPS) ==================

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
            else:
                return "DOM结构解析异常"
        except Exception:
            return "提取过程报错"
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
            clickable_link = f"<a href='{link}' target='_blank' style='color:#1a73e8; text-decoration:underline;'>{highlight_title}</a>"

            return f"{clickable_link} <br><span style='font-size:11px;color:#888;'>({pub_date})</span>"
    except: pass
    return "系统未检索到本年度 CIPS 官方重磅数据"

def get_cnh_hibor():
    """【终极修复】直捣黄龙：穿透 iframe 抓取中银香港底层真实数据源"""
    real_api_url = "https://www.bochk.com/whk/rates/cnyHiborRates/cnyHiborRates-enquiry.action?lang=cn"

    html = fetch_html_with_fallback(real_api_url)

    if html:
        try:
            on_match = re.search(r'(?:Overnight|隔夜)[^\d]*?([\d\.]+)\s*%?', html, re.IGNORECASE)
            if on_match: return float(on_match.group(1)), "隔夜(BOC)"

            w1_match = re.search(r'(?:1\s*Week|1星期|1周)[^\d]*?([\d\.]+)\s*%?', html, re.IGNORECASE)
            if w1_match: return float(w1_match.group(1)), "1周(BOC)"

            m1_match = re.search(r'(?:1\s*Month|1个月)[^\d]*?([\d\.]+)\s*%?', html, re.IGNORECASE)
            if m1_match: return float(m1_match.group(1)), "1个月(BOC)"
        except:
            pass

    tickers = [("CNHON=X", "隔夜"), ("CNH1WD=X", "1周"), ("CNH1MD=X", "1个月")]
    for ticker, name in tickers:
        val = get_yahoo_quote(ticker)
        if val is not None: return val, f"{name}(YQ)"

    for ticker, name in tickers:
        val, _ = get_yahoo_history(ticker)
        if val is not None: return val, f"{name}(YH)"

    return None, "官方与备用全断流"

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
    """【新增】一阶导动量加速过滤器 (Momentum Z-Score)"""
    if not history or len(history) < window + 20:
        return 0.0
    # 计算特定窗口期的差值序列（动量）
    momentum_series = [history[i] - history[i+window] for i in range(len(history)-window)]
    # 返回动量序列的 Robust Z-Score，反映当下的加速度是否异常极值
    return calc_robust_z(momentum_series[0], momentum_series)

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

def pos_to_str(pos):
    pct = int(pos * 100)
    if pct == 0: return "🚫 空仓 (0%)"
    if pct <= 30: return f"🟡 试探 ({pct}%)"
    if pct <= 70: return f"🟢 标配 ({pct}%)"
    return f"🔥 重仓 ({pct}%)"

def fmt_val(val, suffix="", precision=2):
    if val is None: return "[无报价]"
    return f"{val:.{precision}f}{suffix}"

# ================== 4. 因子提取与量化计算 ==================

def extract_factors(api_key):
    f = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
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
            "hkd_cny": executor.submit(get_yahoo_history, "HKDCNY=X"),
            "cny_hkd": executor.submit(get_yahoo_history, "CNYHKD=X"),
            "lme": executor.submit(get_lme_spread),
            "walcl": executor.submit(get_fred_history, "WALCL", api_key, limit=300, force_daily=True),
            "tga": executor.submit(get_fred_history, "WTREGEN", api_key, limit=300, force_daily=True),
            "voo": executor.submit(get_yahoo_history, "VOO"),
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
        hkd_cny_cur, _ = futures["hkd_cny"].result()
        cny_hkd_cur, _ = futures["cny_hkd"].result()
        lme_spread = futures["lme"].result()
        _, walcl = futures["walcl"].result()
        _, tga = futures["tga"].result()

        f['voo_cur'], f['voo_hist'] = futures["voo"].result()
        f['gold_cur'], f['gold_hist'] = futures["gold"].result()
        f['copx_cur'], f['copx_hist'] = futures["copx"].result()

    spread_pips = f"{(usd_cnh_cur - usd_cny_cur) * 10000:.0f} pips" if (usd_cnh_cur and usd_cny_cur) else "无报价"

    f['raw'] = {
        'hy': hy_cur, 'rr': rr_cur, 'us10': us10_cur, 'dxy': dxy_cur,
        'rrp': rrp_cur, 't10': t10_cur, 'yc': yc_cur,
        'hibor': hibor_cur, 'hibor_name': hibor_name,
        'lme_spread': lme_spread,
        'usd_cnh': usd_cnh_cur, 'usd_cny': usd_cny_cur,
        'hkd_cny': hkd_cny_cur, 'cny_hkd': cny_hkd_cur,
        'cnh_cny_spread': spread_pips
    }

    f['z_vix'] = calc_robust_z(vix[0], vix) if vix else 0.0
    f['z_move'] = calc_robust_z(move[0], move) if move else 0.0
    f['z_hy'] = calc_robust_z(hy[0], hy) if hy else 0.0
    f['z_realrate'] = calc_robust_z(rr[0], rr) if rr else 0.0
    f['z_us10y'] = calc_robust_z(us10[0], us10) if us10 else 0.0
    f['z_dxy'] = calc_robust_z(dxy[0], dxy) if dxy else 0.0

    # 【新增】引入实际利率的动量极值因子 (加速度)
    f['z_realrate_mom'] = calc_momentum_z(rr, window=3)

    f['liq_delta_z'] = 0.0
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

    return f

def calculate_quant_execution(f):
    pos, const = {}, {}
    risk_comp = max(f['z_vix'], f['z_move'], f['z_hy']) * 0.6 + sum([f['z_vix'], f['z_move'], f['z_hy']])/3.0 * 0.4

    w_liq, w_risk, w_rate = (0.3, 1.2, 0.8) if f['z_us10y'] > 1.5 else (0.7, 0.8, 0.4)

    z_voo = (f['liq_delta_z'] * w_liq) - (risk_comp * w_risk) - (f['z_us10y'] * w_rate)
    z_gold = -(f['z_realrate'] * 1.0) - (f['z_dxy'] * 0.4) + (risk_comp * 0.3)
    z_copx = -(f['z_dxy'] * 0.6) + (f['liq_delta_z'] * w_liq) - (risk_comp * w_risk)

    def apply_filters(price, history, base_z):
        if not history or len(history) < 210: return z_to_position(base_z), "数据不足"
        ma200 = calc_ma(history, 200)
        slope = calc_ma_slope(history, 50, 10)
        vol_z = calc_volatility_z(history, 20)

        target = z_to_position(base_z)
        msgs = []
        if vol_z > 1.5:
            target *= 0.5; msgs.append("高波动降仓")
        if price < ma200 and slope < 0:
            return 0.0, "🚨 破位向下(空仓)"
        elif price >= ma200 and slope < 0:
            target = min(target, 0.3); msgs.append("⚠️ 均线背离(限仓)")
        elif price < ma200 and slope > 0:
            target = min(target, 0.3); msgs.append("⚠️ 熊市反弹(限仓)")
        return target, " | ".join(msgs) if msgs else "✅ 健康"

    pos["VOO"], const["VOO"] = apply_filters(f['voo_cur'], f['voo_hist'], z_voo)
    pos["GOLD"], const["GOLD"] = apply_filters(f['gold_cur'], f['gold_hist'], z_gold)
    pos["COPX"], const["COPX"] = apply_filters(f['copx_cur'], f['copx_hist'], z_copx)

    # 【新增风控】如果实际利率出现陡峭加速上行 (动量 Z > 1.5)，黄金底层估值受压，强制削减一半敞口
    if f.get('z_realrate_mom', 0.0) > 1.5:
        pos["GOLD"] *= 0.5
        if const["GOLD"] == "✅ 健康":
            const["GOLD"] = "🚨 实际利率加速上行"
        else:
            const["GOLD"] += " | 🚨 实际利率加速上行"

    if pos["VOO"] + pos["COPX"] > 1.2:
        scale = 1.2 / (pos["VOO"] + pos["COPX"])
        pos["VOO"] *= scale; pos["COPX"] *= scale
        const["PORTFOLIO"] = "⚖️ 风险敞口过载，按比例压缩"

    if risk_comp > 2.5:
        pos["VOO"] *= 0.3; pos["COPX"] *= 0.3
        const["GLOBAL"] = "🔥 系统危机：保留 30% 底仓防深 V"

    return pos, risk_comp, const, f

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

    pos, risk_comp, constraints, raw_f = calculate_quant_execution(f)
    raw = f['raw']

    hibor_name = raw.get('hibor_name', '隔夜')
    desc = generate_dynamic_analysis(raw, raw_f, risk_comp)

    md = "## 🗺️ 市场宽度与全景热力图 (Market Breadth)\n\n"
    md += "> 提示：Finviz 底层为防爬虫实时渲染，点击下方加密通道直达原生热力图：\n\n"
    md += "👉 **[点击查看：美股 标普500 热力图 (S&P 500)](https://finviz.com/map.ashx?t=sec)**\n\n"
    md += "👉 **[点击查看：全球核心资产 热力图 (World)](https://finviz.com/map.ashx?t=geo)**\n\n"
    md += "---\n\n"

    md += "## 🤖 宏观策略控制台 (Signal → Portfolio 闭环)\n\n"
    if "GLOBAL" in constraints: md += f"> **🚨 熔断控制**：{constraints['GLOBAL']}\n\n"
    if "PORTFOLIO" in constraints: md += f"> **⚖️ 组合风控**：{constraints['PORTFOLIO']}\n\n"

    md += "| 资产 | 标的 | 今日目标仓位 | 状态引擎 (Regime & Filter) |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    md += f"| **美股大盘** | VOO | **{pos_to_str(pos['VOO'])}** | {constraints['VOO']} |\n"
    md += f"| **避险黄金** | 18.HK | **{pos_to_str(pos['GOLD'])}** | {constraints['GOLD']} |\n"
    md += f"| **大宗商品** | COPX | **{pos_to_str(pos['COPX'])}** | {constraints['COPX']} |\n\n"

    md += "## 📈 核心宏观全景面板 (指标判读分析)\n\n"
    md += "| 变量名称 | 最新绝对数值 | 因子状态 (Z-Score) | 核心驱动逻辑 (今日动态判读) |\n"
    md += "| :--- | :--- | :--- | :--- |\n"

    md += f"| **A. LME铜升贴水** | **{raw['lme_spread']}** | 物理逼空 | {format_cell(desc['A'], '现货贵于期货(>0)说明实体库存极缺')} |\n"
    md += f"| **B. 逆回购(RRP)** | **{fmt_val(raw['rrp'], ' B', 1)}** | **{fmt_val(raw_f['liq_delta_z'])}** (净流动性) | {format_cell(desc['B'], '水库释放器，连同TGA构成美元总水位')} |\n"

    fx_str = f"在岸(CNY): **{fmt_val(raw['usd_cny'], precision=4)}**<br>离岸(CNH): **{fmt_val(raw['usd_cnh'], precision=4)}**<br>港币兑RMB: **{fmt_val(raw['hkd_cny'], precision=4)}**"
    md += f"| **C. 核心实时汇率** | {fx_str} | 价差: **{raw['cnh_cny_spread']}** | {format_cell(desc['C'], '价差剧烈扩大(>300)意味外资正在做空中国资产')} |\n"

    md += f"| **D. 盈亏通胀率** | **{fmt_val(raw['t10'], '%')}** | 远期定价 | {format_cell(desc['D'], '黄金的助推剂，突破前高需重仓')} |\n"

    # 【UI优化】为 TIPS 添加灰色的 (T-1, FRED) 机构严谨标注
    md += f"| **E. 实际利率(TIPS)**| **{fmt_val(raw['rr'], '%')}** <span style='font-size:11px;color:#888;'>(T-1, FRED)</span> | **{fmt_val(raw_f['z_realrate'])}** | {format_cell(desc['E'], '黄金绝对反向锚，极高位时压制一切估值')} |\n"

    md += f"| **F. 高收益债利差** | **{fmt_val(raw['hy'], '%')}** | **{fmt_val(raw_f['z_hy'])}** (信用) | {format_cell(desc['F'], '企业违约生死线，破 5% 亮红灯')} |\n"
    md += f"| **G. 长短端利差** | **{fmt_val(raw['yc'], '%')}** | 周期警报 | {format_cell(desc['G'], '10Y-2Y 倒挂解除瞬间，通常衰退正式兑现')} |\n"
    md += f"| **H. 美元指数(DXY)** | **{fmt_val(raw['dxy'])}** | **{fmt_val(raw_f['z_dxy'])}** | {format_cell(desc['H'], '全球流动性虹吸指标，走强利空大宗')} |\n"
    md += f"| **I. 复合风险指数** | 综合测算 | **{fmt_val(risk_comp)}** | {format_cell(desc['I'], '结合 VIX, MOVE, HY。>1.5严禁逆势重仓')} |\n"
    md += f"| **J. 跨境流动性(HIBOR)**| **{fmt_val(raw['hibor'], '%')}** ({hibor_name}) | 离岸人民币 | {format_cell(desc['J'], 'CNH 隔夜拆借利率暴涨说明离岸系统遭抽水')} |\n"
    md += f"| ↳ *CIPS 结构面新闻* | **最新快报** | <span style='color:#555;'>{cips_news}</span> | <span style='font-size:11px; font-style:italic; color:#666;'>(长线低频跟踪，反映人民币国际化实质进度)</span> |\n"

    return md + "\n---\n"
