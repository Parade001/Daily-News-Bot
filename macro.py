import math
import statistics
import urllib.parse
import re
import time
import feedparser
from http_client import shared_session

# ================== 1. 底层网络与容错 ==================

def fetch_with_retry(url, is_json=False, max_retries=3):
    """带指数退避的重试机制，保障云端请求成功率"""
    for i in range(max_retries):
        try:
            r = shared_session.get(url, timeout=10)
            if r.status_code == 200: 
                return r.json() if is_json else r.text
        except: 
            time.sleep(2 ** i)
    return None

def fetch_html_with_fallback(url):
    """三层跳板穿透，专治 Cloudflare WAF 拦截"""
    try:
        r = shared_session.get(url, timeout=10)
        if r.status_code == 200 and "Cloudflare" not in r.text: return r.text
    except: pass
    try:
        r = shared_session.get(f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}", timeout=15)
        if r.status_code == 200 and "Cloudflare" not in r.text: return r.text
    except: pass
    try:
        r = shared_session.get(f"https://corsproxy.io/?{urllib.parse.quote(url)}", timeout=15)
        if r.status_code == 200 and "Cloudflare" not in r.text: return r.text
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

# ================== 2. 专项数据抓取 (LME / CNH / CIPS) ==================

def get_lme_spread():
    url = "https://www.westmetall.com/en/markdaten.php?action=show_table&field=LME_Cu_cash"
    html = fetch_html_with_fallback(url)
    if html and '3-months' in html:
        try:
            rows = re.findall(r'<tr>(.*?)</tr>', html, re.DOTALL)
            for row in rows:
                cols = re.findall(r'<td>(.*?)</td>', row, re.DOTALL)
                if len(cols) >= 3:
                    cash = float(re.sub(r'[^0-9\.\-]', '', cols[1].replace(',', '')))
                    m3 = float(re.sub(r'[^0-9\.\-]', '', cols[2].replace(',', '')))
                    return f"${cash - m3:.2f}"
        except: pass
    return "解析失败"

def get_cnh_cny_spread():
    cnh_cur, _ = get_yahoo_history("USDCNH=X")
    cny_cur, _ = get_yahoo_history("USDCNY=X")
    if cnh_cur and cny_cur:
        return f"{(cnh_cur - cny_cur) * 10000:.0f} pips"
    return "接口异常"

def get_cips_structural_news():
    """低频长线指标：抓取 CIPS 新闻动态以观测结构性进展"""
    url = "https://news.google.com/rss/search?q=CIPS+%E4%BA%A4%E6%98%93+%E9%87%91%E9%A2%9D+OR+%E7%AC%94%E6%95%B0+when:1m&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        feed = feedparser.parse(url)
        if feed.entries:
            latest_news = feed.entries[0]
            title = latest_news.title.replace("|", "-") # 防止破坏 Markdown 表格
            pub_date = latest_news.published if hasattr(latest_news, 'published') else "近期"
            # 粗略高亮金额
            highlight_title = re.sub(r'(\d+(?:\.\d+)?(?:万亿|亿|万))', r'**\1**', title)
            return f"{highlight_title} <br><span style='font-size:11px;color:#888;'>({pub_date})</span>"
    except: pass
    return "本月暂无 CIPS 官方重磅数据发布"

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
    """安全格式化拦截器，防止界面出现 None%"""
    if val is None: return "[无报价]"
    return f"{val:.{precision}f}{suffix}"

# ================== 4. 因子提取与量化计算 ==================

def extract_factors(api_key):
    f = {}
    _, vix = get_yahoo_history("^VIX")
    _, move = get_yahoo_history("^MOVE")
    hy_cur, hy = get_fred_history("BAMLH0A0HYM2", api_key)
    rr_cur, rr = get_fred_history("DFII10", api_key)
    us10_cur, us10 = get_fred_history("DGS10", api_key)
    dxy_cur, dxy = get_yahoo_history("DX-Y.NYB")
    rrp_cur, rrp = get_fred_history("RRPONTSYD", api_key, force_daily=True)
    t10_cur, t10 = get_fred_history("T10BEI", api_key)
    yc_cur, yc = get_fred_history("T10Y2Y", api_key)
    hibor_cur, _ = get_yahoo_history("CNHON=X")
    
    # 存入 raw 字典供经典面板渲染
    f['raw'] = {
        'hy': hy_cur, 'rr': rr_cur, 'us10': us10_cur, 'dxy': dxy_cur, 
        'rrp': rrp_cur, 't10': t10_cur, 'yc': yc_cur, 'hibor': hibor_cur,
        'lme_spread': get_lme_spread(), 'cnh_cny': get_cnh_cny_spread()
    }
    
    f['z_vix'] = calc_robust_z(vix[0], vix) if vix else 0.0
    f['z_move'] = calc_robust_z(move[0], move) if move else 0.0
    f['z_hy'] = calc_robust_z(hy[0], hy) if hy else 0.0
    f['z_realrate'] = calc_robust_z(rr[0], rr) if rr else 0.0
    f['z_us10y'] = calc_robust_z(us10[0], us10) if us10 else 0.0
    f['z_dxy'] = calc_robust_z(dxy[0], dxy) if dxy else 0.0

    _, walcl = get_fred_history("WALCL", api_key, limit=300, force_daily=True)
    _, tga = get_fred_history("WTREGEN", api_key, limit=300, force_daily=True)
    
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

    f['voo_cur'], f['voo_hist'] = get_yahoo_history("VOO")
    f['gold_cur'], f['gold_hist'] = get_yahoo_history("GC=F")
    f['copx_cur'], f['copx_hist'] = get_yahoo_history("COPX")

    return f

def calculate_quant_execution(f):
    pos, const = {}, {}
    risk_comp = max(f['z_vix'], f['z_move'], f['z_hy']) * 0.6 + sum([f['z_vix'], f['z_move'], f['z_hy']])/3.0 * 0.4
    
    # 宏观状态切换 (Regime Switch)
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

    # 跨资产风控
    if pos["VOO"] + pos["COPX"] > 1.2:
        scale = 1.2 / (pos["VOO"] + pos["COPX"])
        pos["VOO"] *= scale; pos["COPX"] *= scale
        const["PORTFOLIO"] = "⚖️ 风险敞口过载，按比例压缩"

    # 软性熔断底仓机制
    if risk_comp > 2.5:
        pos["VOO"] *= 0.3; pos["COPX"] *= 0.3
        const["GLOBAL"] = "🔥 系统危机：保留 30% 底仓防深 V"

    return pos, risk_comp, const, f

# ================== 5. 组装最终面板 ==================

def fetch_macro_indicators(fred_api_key=None):
    f = extract_factors(fred_api_key)
    pos, risk_comp, constraints, raw_f = calculate_quant_execution(f)
    raw = f['raw']
    cips_news = get_cips_structural_news()
    
    # [模块一] 热力图直达通道
    md = "## 🗺️ 市场宽度与全景热力图 (Market Breadth)\n\n"
    md += "> 提示：Finviz 底层为防爬虫实时渲染，点击下方加密通道直达原生热力图：\n\n"
    md += "👉 **[点击查看：美股 标普500 热力图 (S&P 500)](https://finviz.com/map.ashx?t=sec)**\n\n"
    md += "👉 **[点击查看：全球核心资产 热力图 (World)](https://finviz.com/map.ashx?t=geo)**\n\n"
    md += "---\n\n"

    # [模块二] 量化控制台 (执行引擎)
    md += "## 🤖 宏观策略控制台 (Signal → Portfolio 闭环)\n\n"
    if "GLOBAL" in constraints: md += f"> **🚨 熔断控制**：{constraints['GLOBAL']}\n\n"
    if "PORTFOLIO" in constraints: md += f"> **⚖️ 组合风控**：{constraints['PORTFOLIO']}\n\n"

    md += "| 资产 | 标的 | 今日目标仓位 | 状态引擎 (Regime & Filter) |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    md += f"| **美股大盘** | VOO | **{pos_to_str(pos['VOO'])}** | {constraints['VOO']} |\n"
    md += f"| **避险黄金** | 18.HK | **{pos_to_str(pos['GOLD'])}** | {constraints['GOLD']} |\n"
    md += f"| **大宗商品** | COPX | **{pos_to_str(pos['COPX'])}** | {constraints['COPX']} |\n\n"
    
    # [模块三] 经典核心观测面板 (全量指标原值观测)
    md += "## 📈 核心宏观全景面板 (经典全量指标观测)\n\n"
    md += "| 变量名称 | 最新绝对数值 | 因子状态 (Z-Score) | 核心驱动逻辑 |\n"
    md += "| :--- | :--- | :--- | :--- |\n"
    
    md += f"| **A. LME铜升贴水** | **{raw['lme_spread']}** | 物理逼空 | 现货贵于期货(>0)说明实体库存极缺。 |\n"
    md += f"| **B. 逆回购(RRP)** | **{fmt_val(raw['rrp'], ' B', 1)}** | **{fmt_val(raw_f['liq_delta_z'])}** (净流动性) | 水库释放器。连同TGA构成核心美元水位。 |\n"
    md += f"| **C. CNH-CNY 价差** | **{raw['cnh_cny']}** | 离岸情绪 | 价差扩大意味着外资在大肆做空人民币。 |\n"
    md += f"| **D. 盈亏通胀率** | **{fmt_val(raw['t10'], '%')}** | 远期定价 | 黄金的助推剂，突破前高需重仓。 |\n"
    md += f"| **E. 实际利率(TIPS)**| **{fmt_val(raw['rr'], '%')}** | **{fmt_val(raw_f['z_realrate'])}** | 黄金绝对反向锚。极高位时压制一切估值。 |\n"
    md += f"| **F. 高收益债利差** | **{fmt_val(raw['hy'], '%')}** | **{fmt_val(raw_f['z_hy'])}** (信用) | 企业违约生死线，破 5% 亮红灯。 |\n"
    md += f"| **G. 长短端利差** | **{fmt_val(raw['yc'], '%')}** | 周期警报 | 10Y-2Y 倒挂解除瞬间，通常衰退正式兑现。 |\n"
    md += f"| **H. 美元指数(DXY)** | **{fmt_val(raw['dxy'])}** | **{fmt_val(raw_f['z_dxy'])}** | 全球流动性虹吸指标，走强利空大宗。 |\n"
    md += f"| **I. 复合风险指数** | 综合测算 | **{fmt_val(risk_comp)}** | 结合 VIX, MOVE, HY。>1.5严禁逆势重仓。 |\n"
    md += f"| **J. 跨境流动性(HIBOR)**| **{fmt_val(raw['hibor'], '%')}** | 离岸人民币 | CNH 隔夜利率暴涨说明离岸系统遭抽水。 |\n"
    md += f"| ↳ *CIPS 结构面新闻* | **最新快报** | {cips_news} | 长线低频跟踪，反映人民币国际化实质进度。 |\n"

    return md + "\n---\n"
