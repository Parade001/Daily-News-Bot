import math
import statistics
import urllib.parse
import re
import time
from http_client import shared_session

# ================== 1. 底层网络与容错 ==================

def fetch_with_retry(url, is_json=False, max_retries=3):
    for i in range(max_retries):
        try:
            r = shared_session.get(url, timeout=10)
            if r.status_code == 200:
                return r.json() if is_json else r.text
        except Exception:
            time.sleep(2 ** i)
    return None

def get_fred_history(series_id, api_key, limit=260, force_daily=False):
    if not api_key: return None, []
    freq_param = "&frequency=d" if force_daily else ""
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit={limit}{freq_param}"
    data = fetch_with_retry(url, is_json=True)
    history = []
    if data and 'observations' in data:
        for item in data['observations']:
            val = item.get('value', '.')
            if val not in ['.', '', 'NaN', None]:
                history.append(float(val))
    if not history: return None, []
    return history[0], history

def get_yahoo_history(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2y"
    data = fetch_with_retry(url, is_json=True)
    try:
        closes = data['chart']['result'][0]['indicators']['quote'][0]['close']
        history = [c for c in closes if c is not None]
        history.reverse()
        if history: return history[0], history
    except: pass
    return None, []

# ================== 2. 量化特征与信号处理 ==================

def calc_robust_z(current, history):
    if not history or len(history) < 20: return 0.0
    med = statistics.median(history)
    mad = statistics.median([abs(x - med) for x in history])
    adjusted_mad = mad * 1.4826
    if adjusted_mad == 0: return 0.0
    return (current - med) / adjusted_mad

def calc_ma(history, periods):
    if not history or len(history) < periods: return None
    return sum(history[:periods]) / periods

def calc_ma_slope(history, ma_period=50, lookback=10):
    if not history or len(history) < ma_period + lookback: return 0.0
    ma_today = calc_ma(history[:ma_period], ma_period)
    ma_past = calc_ma(history[lookback:lookback+ma_period], ma_period)
    if not ma_past or ma_past == 0: return 0.0
    return (ma_today - ma_past) / ma_past

def calc_ema(history, span=10):
    if not history: return []
    rev_hist = list(reversed(history))
    ema = [rev_hist[0]]
    alpha = 2.0 / (span + 1.0)
    for i in range(1, len(rev_hist)):
        ema.append(rev_hist[i] * alpha + ema[-1] * (1.0 - alpha))
    ema.reverse()
    return ema

def calc_volatility_regime(price_history, window=20):
    if not price_history or len(price_history) < window + 260:
        return 0.0
    vol_hist = []
    for i in range(len(price_history) - window):
        slice_p = price_history[i:i+window+1]
        rets = [(slice_p[j] - slice_p[j+1])/slice_p[j+1] for j in range(window)]
        mean_ret = sum(rets)/window
        var = sum((r - mean_ret)**2 for r in rets) / (window - 1)
        vol_hist.append(math.sqrt(var) * math.sqrt(252))
    return calc_robust_z(vol_hist[0], vol_hist)

def z_to_position(z):
    """【核心升级】分段线性映射：解决极端行情下 tanh 函数饱和失效的问题"""
    if z <= 0: return 0.0
    if z <= 1.0: return z * 0.3                # 0~1 区间：0% ~ 30% 底仓
    if z <= 2.0: return 0.3 + (z - 1.0) * 0.4  # 1~2 区间：30% ~ 70% 标配
    if z <= 3.0: return 0.7 + (z - 2.0) * 0.3  # 2~3 区间：70% ~ 100% 重仓
    return 1.0

def pos_to_str(pos):
    pct = int(pos * 100)
    if pct == 0: return "🚫 空仓 (0%)"
    if pct <= 30: return f"🟡 试探 ({pct}%)"
    if pct <= 70: return f"🟢 标配 ({pct}%)"
    return f"🔥 重仓 ({pct}%)"

# ================== 3. 宏观因子立方体 ==================

def extract_factors(api_key):
    f = {}

    _, vix_hist = get_yahoo_history("^VIX")
    _, move_hist = get_yahoo_history("^MOVE")
    _, hy_hist = get_fred_history("BAMLH0A0HYM2", api_key)
    _, realrate_hist = get_fred_history("DFII10", api_key)
    _, us10y_hist = get_fred_history("DGS10", api_key)
    _, dxy_hist = get_yahoo_history("DX-Y.NYB")

    f['z_vix'] = calc_robust_z(vix_hist[0], vix_hist) if vix_hist else 0.0
    f['z_move'] = calc_robust_z(move_hist[0], move_hist) if move_hist else 0.0
    f['z_hy'] = calc_robust_z(hy_hist[0], hy_hist) if hy_hist else 0.0
    f['z_realrate'] = calc_robust_z(realrate_hist[0], realrate_hist) if realrate_hist else 0.0
    f['z_us10y'] = calc_robust_z(us10y_hist[0], us10y_hist) if us10y_hist else 0.0
    f['z_dxy'] = calc_robust_z(dxy_hist[0], dxy_hist) if dxy_hist else 0.0

    _, walcl_hist = get_fred_history("WALCL", api_key, limit=300, force_daily=True)
    _, rrp_hist = get_fred_history("RRPONTSYD", api_key, limit=300, force_daily=True)
    _, tga_hist = get_fred_history("WTREGEN", api_key, limit=300, force_daily=True)

    f['liq_delta_z'] = 0.0
    if walcl_hist and rrp_hist and tga_hist:
        min_len = min(len(walcl_hist), len(rrp_hist), len(tga_hist))
        if min_len > 30:
            raw_deltas = []
            for i in range(min_len - 20):
                l_cur = walcl_hist[i] - rrp_hist[i] - tga_hist[i]
                l_past = walcl_hist[i+20] - rrp_hist[i+20] - tga_hist[i+20]
                raw_deltas.append(l_cur - l_past)
            smoothed_deltas = calc_ema(raw_deltas, span=10)
            f['liq_delta_z'] = calc_robust_z(smoothed_deltas[0], smoothed_deltas)

    f['voo_cur'], f['voo_hist'] = get_yahoo_history("VOO")
    f['gold_cur'], f['gold_hist'] = get_yahoo_history("GC=F")
    f['copx_cur'], f['copx_hist'] = get_yahoo_history("COPX")

    return f

# ================== 4. 实盘执行层 (Execution Layer) ==================

def calculate_quant_execution(f):
    pos = {}
    constraints = {}

    # 1. 风险与 Regime 识别
    risk_composite = max(f['z_vix'], f['z_move'], f['z_hy']) * 0.6 + ((f['z_vix'] + f['z_move'] + f['z_hy'])/3.0) * 0.4

    # 【核心升级】Regime Switch: 判断是否处于高利率惩罚区间
    if f['z_us10y'] > 1.5:
        w_liq, w_risk, w_rate = 0.3, 1.2, 0.8  # 高息时代：极度厌恶风险，流动性效用减弱
    else:
        w_liq, w_risk, w_rate = 0.7, 0.8, 0.4  # 宽货币时代：流动性主导

    # 2. 因子暴露计算 (Factor Exposure)
    z_voo = (f['liq_delta_z'] * w_liq) - (risk_composite * w_risk) - (f['z_us10y'] * w_rate)
    z_gold = -(f['z_realrate'] * 1.0) - (f['z_dxy'] * 0.4) + (risk_composite * 0.3)
    z_copx = -(f['z_dxy'] * 0.6) + (f['liq_delta_z'] * w_liq) - (risk_composite * w_risk)

    # 3. 单资产过滤 (Trend & Volatility Filter)
    def apply_filters(current_price, history, base_z):
        if not history or len(history) < 210: return z_to_position(base_z), ""

        ma200 = calc_ma(history, 200)
        slope = calc_ma_slope(history, 50, 10)
        vol_z = calc_volatility_regime(history, 20)

        target_p = z_to_position(base_z)
        msgs = []

        if vol_z > 1.5:
            target_p *= 0.5  # 高波动期强制降杠杆
            msgs.append("高波动降仓")

        if current_price < ma200 and slope < 0:
            target_p = 0.0
            msgs.append("🚨 破位向下(强制空仓)")
        elif current_price >= ma200 and slope < 0:
            target_p = min(target_p, 0.3)
            msgs.append("⚠️ 均线背离(限仓30%)")
        elif current_price < ma200 and slope > 0:
            target_p = min(target_p, 0.3)
            msgs.append("⚠️ 熊市反弹(限仓30%)")

        return target_p, " | ".join(msgs) if msgs else "✅ 健康"

    pos["VOO"], constraints["VOO"] = apply_filters(f['voo_cur'], f['voo_hist'], z_voo)
    pos["GOLD"], constraints["GOLD"] = apply_filters(f['gold_cur'], f['gold_hist'], z_gold)
    pos["COPX"], constraints["COPX"] = apply_filters(f['copx_cur'], f['copx_hist'], z_copx)

    # 4. 【核心升级】跨资产相关性约束 (Portfolio Level Constraint)
    # VOO 和 COPX 在宏观衰退/繁荣周期高度正相关，限制 Risk-On 总敞口
    total_risk_on = pos["VOO"] + pos["COPX"]
    if total_risk_on > 1.2:
        scale = 1.2 / total_risk_on
        pos["VOO"] *= scale
        pos["COPX"] *= scale
        constraints["PORTFOLIO"] = f"⚖️ 触发组合共振约束：总 Risk-On 敞口过载，等比例压缩至上限 120%"

    # 5. 【核心升级】软性熔断底仓机制 (Soft Circuit Breaker)
    if risk_composite > 2.5:
        pos["VOO"] *= 0.3
        pos["COPX"] *= 0.3
        constraints["GLOBAL"] = "🔥 系统危机 (Risk Z>2.5)：执行软熔断，保留 30% 目标底仓捕捉深 V 反弹"

    return pos, risk_composite, constraints, f

# ================== 5. 渲染输出 ==================

def fetch_macro_indicators(fred_api_key=None):
    f = extract_factors(fred_api_key)
    pos, risk_comp, constraints, raw_f = calculate_quant_execution(f)

    # ================== 新增：市场宽度与热力图入口 ==================
    md = "## 🗺️ 市场宽度与全景热力图 (Market Breadth)\n\n"
    md += "> ⚠️ **监控站提示**：Finviz 热力图为底层实时渲染。请直接点击下方加密通道，利用本地网络环境查看全景。\n\n"

    # 使用无序列表和清晰的超链接引导
    md += "- 🇺🇸 **[点击直达：美股标普 500 热力图 (S&P 500)](https://finviz.com/map.ashx?t=sec)**\n"
    md += "- 🌍 **[点击直达：全球核心资产 热力图 (World)](https://finviz.com/map.ashx?t=geo)**\n\n"
    md += "---\n\n"
    md = "## 🤖 宏观策略控制台 (Signal → Portfolio 闭环)\n\n"

    if "GLOBAL" in constraints:
        md += f"> **🚨 熔断控制**：{constraints['GLOBAL']}\n\n"
    if "PORTFOLIO" in constraints:
        md += f"> **⚖️ 组合风控**：{constraints['PORTFOLIO']}\n\n"

    md += "> **摩擦成本约束 (Slippage/Fee)**：若以下【目标仓位】与你【当前账户真实仓位】差值 `< 10%`，请忽略本次信号，避免无效交易损耗本金。\n\n"

    md += "| 资产 | 标的 | 今日目标仓位 | 状态引擎 (Regime & Filter) |\n"
    md += "| :--- | :--- | :--- | :--- |\n"

    md += f"| **美股大盘** | VOO | **{pos_to_str(pos['VOO'])}** | {constraints['VOO']} |\n"
    md += f"| **避险黄金** | 18.HK | **{pos_to_str(pos['GOLD'])}** | {constraints['GOLD']} |\n"
    md += f"| **大宗商品** | COPX | **{pos_to_str(pos['COPX'])}** | {constraints['COPX']} |\n\n"

    return md + "\n---\n"
