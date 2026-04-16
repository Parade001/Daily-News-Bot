import concurrent.futures
from data_fetcher import (
    get_fred_history, get_yahoo_history, get_cnh_hibor,
    get_lme_spread, get_cips_structural_news
)
from quant_calc import calc_robust_z, calc_momentum_z, calc_ema, get_ret
from risk_engine import execute_quant_strategy

# ================== 辅助格式化函数 ==================

def get_daily_change(history):
    if not history or len(history) < 2: return "0.00%"
    chg = get_ret(history) * 100
    color = "#d93025" if chg < 0 else ("#1e8e3e" if chg > 0 else "#555")
    sign = "+" if chg > 0 else ""
    return f"<span style='color:{color}; font-weight:bold;'>{sign}{chg:.2f}%</span>"

def pos_to_str(pos):
    pct = int(pos * 100)
    return "0%" if pct == 0 else f"{pct}%"

def fmt_val(val, suffix="", precision=2):
    return "[无报价]" if val is None else f"{val:.{precision}f}{suffix}"

def format_cell(dynamic_text, static_text):
    return f"{dynamic_text}<br><span style='font-size:11px; font-style:italic; color:#666;'>({static_text})</span>"

# ================== 提取核心因子 (主线程池) ==================

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
            "hkd_cny": executor.submit(get_yahoo_history, "HKDCNY=X"),
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
        hkd_cny_cur, _ = futures["hkd_cny"].result()
        lme_spread = futures["lme"].result()
        _, walcl = futures["walcl"].result()
        _, tga = futures["tga"].result()

        f['voo_cur'], f['voo_hist'] = futures["voo"].result()
        f['qqq_cur'], f['qqq_hist'] = futures["qqq"].result()
        f['gold_cur'], f['gold_hist'] = futures["gold"].result()
        f['copx_cur'], f['copx_hist'] = futures["copx"].result()

    cnh_stress_pips = (usd_cnh_cur - usd_cny_cur) * 10000 if (usd_cnh_cur and usd_cny_cur) else 0.0
    spread_pips_str = f"{cnh_stress_pips:.0f} pips" if cnh_stress_pips else "无报价"

    f['raw'] = {
        'hy': hy_cur, 'rr': rr_cur, 'us10': us10_cur, 'dxy': dxy_cur,
        'rrp': rrp_cur, 't10': t10_cur, 'yc': yc_cur,
        'hibor': hibor_cur, 'hibor_name': hibor_name,
        'lme_spread': lme_spread,
        'usd_cnh': usd_cnh_cur, 'usd_cny': usd_cny_cur,
        'hkd_cny': hkd_cny_cur,
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

    f['liq_delta_z'], f['liq_impulse'] = 0.0, 0.0
    if walcl and rrp and tga:
        min_len = min(len(walcl), len(rrp), len(tga))
        if min_len > 30:
            raw_deltas = [ (walcl[i]-rrp[i]-tga[i]) - (walcl[i+20]-rrp[i+20]-tga[i+20]) for i in range(min_len - 20) ]
            smoothed = calc_ema(raw_deltas, span=10)
            f['liq_delta_z'] = calc_robust_z(smoothed[0], smoothed) if smoothed else 0.0
            liq_mom_z = calc_momentum_z(smoothed, window=5) if smoothed else 0.0
            f['liq_impulse'] = f['liq_delta_z'] + 0.5 * liq_mom_z

    return f

# ================== 动态文案解读引擎 ==================

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
    if rc > 2.0: desc['I'] = "🔥 极度恐慌：系统恐慌特征，切入防御避险模式！"
    elif rc > 1.0: desc['I'] = "⚠️ 风险升温：市场情绪脆弱，自动限制多头敞口。"
    else: desc['I'] = "✅ 情绪稳定：市场结构健康，可放心顺势交易。"

    hibor = raw.get('hibor')
    if hibor is not None:
        if hibor > 4.5: desc['J'] = "🚨 离岸抽水：拆借利率飙升，做空人民币成本急剧增加！"
        else: desc['J'] = "✅ 流动性充裕：离岸资金面健康平稳。"
    else: desc['J'] = "⚠️ 场外数据未正常推送"

    return desc

# ================== 最终主入口 ==================

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

    pos, action, risk_comp, constraints, raw_f = execute_quant_strategy(f)
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
