import re
import urllib.parse
import feedparser
from http_client import shared_session

def fetch_with_fallback(url):
    """用于非 API 网站的跳板穿透（保留给 Westmetall 使用）"""
    try:
        r = shared_session.get(url, timeout=10)
        if r.status_code == 200 and "Cloudflare" not in r.text:
            return r.text
    except: pass
    try:
        r = shared_session.get(f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}", timeout=15)
        if r.status_code == 200 and "Cloudflare" not in r.text:
            return r.text
    except: pass
    return None

def get_yahoo_price(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    try:
        r = shared_session.get(url, timeout=10)
        return r.json()['chart']['result'][0]['meta']['regularMarketPrice']
    except: return None

def get_fred_api_value(series_id, api_key):
    """
    【核心升级】FRED 官方 API 请求，彻底免疫拦截，毫秒级响应
    """
    if not api_key:
        return "[未配置 API Key]"

    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit=1"
    try:
        r = shared_session.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if 'observations' in data and len(data['observations']) > 0:
                val = data['observations'][0]['value']
                if val != '.':
                    return val
        return "[API无数据]"
    except: return "[API超时]"

def get_westmetall_spread():
    url = "https://www.westmetall.com/en/markdaten.php?action=show_table&field=LME_Cu_cash"
    html = fetch_with_fallback(url)
    if not html: return "WAF拦截", "无法判断"
    try:
        if '<th>3-months</th>' in html:
            rows = html.split('<th>3-months</th>')[1].split('<tr>')
            for row in rows:
                cols = re.findall(r'<td>(.*?)</td>', row)
                if len(cols) >= 3:
                    date_str = cols[0].strip()
                    cash = float(re.sub(r'[^\d.]', '', cols[1].replace(',', '')))
                    m3 = float(re.sub(r'[^\d.]', '', cols[2].replace(',', '')))
                    spread = cash - m3
                    struct = "🔴 现货溢价" if spread > 0 else "🟢 期货溢价"
                    return f"Cash: ${cash}<br>3M: ${m3}<br>价差: **${spread:.2f}**<br>{struct} ({date_str})", "现货大于期货说明库存极缺"
    except: pass
    return "解析失败", "无法判断"

def get_tc_rc_proxy():
    fcx = get_yahoo_price("FCX")
    jiangxi = get_yahoo_price("0358.HK")
    ratio_str = "[股价接口超时]"
    if fcx and jiangxi:
        ratio = fcx / (jiangxi / 7.8)
        ratio_str = f"矿冶比值: **{ratio:.2f}**<br>*(↑矿端强, ↓冶炼强)*"

    tc_news = "[近期无报价新闻]"
    try:
        feed = feedparser.parse("https://www.mining.com/commodity/copper/feed/")
        for entry in feed.entries[:15]:
            text = entry.title + " " + getattr(entry, 'description', '')
            matches = re.findall(r'(?:TCs?|treatment charges?).*?\$?(\d+(?:\.\d+)?)\s*(?:\/|per)?\s*(?:ton|tonne)', text, re.IGNORECASE)
            vals = [float(m) for m in matches if 5 < float(m) < 150]
            if vals:
                tc_news = f"近期提取 TC: **${vals[0]}/ton**"
                break
    except: pass
    return f"{ratio_str}<br>{tc_news}"

def fetch_macro_indicators(fred_api_key=None):
    macro_md = "## 📈 核心宏观全景面板 (9大领先指标)\n\n"
    macro_md += "| 变量名称 | 最新数值 | 核心运转逻辑 | 宏观映射与决策约束 |\n"
    macro_md += "| :--- | :--- | :--- | :--- |\n"

    # 1. 铜现货升贴水
    spread_data, spread_adv = get_westmetall_spread()
    macro_md += f"| **A. 铜现货升贴水**<br>(LME Cash-to-3M) | {spread_data} | 现货贵于期货说明物理库存极度短缺。 | **观望/中仓**: {spread_adv}。不可做日内依据。 |\n"

    # 2. RRP 逆回购
    rrp_val = get_fred_api_value("RRPONTSYD", fred_api_key)
    macro_md += f"| **B. 逆回购余额**<br>(RRPONTSYD) | **{rrp_val}** (B) | 美元流动性蓄水池。余额下降=流动性释放。 | **重仓**: 余额下行趋势未变，保持做多 VOO。 |\n"

    # 3. 离岸/在岸人民币
    cnh = get_yahoo_price("USDCNH=X")
    cny = get_yahoo_price("USDCNY=X")
    spread_str = f"离岸: {cnh:.4f}<br>在岸: {cny:.4f}<br>价差: **{(cnh - cny) * 10000:.0f} pips**" if cnh and cny else "接口异常"
    macro_md += f"| **C. CNH-CNY 价差**<br>(USDCNH) | {spread_str} | 关注 6.89 防守。CNH反映外资真实情绪。 | **减仓**: 价差持续扩大需警惕避险资金外逃。 |\n"

    # 4. 盈亏平衡通胀
    t10_val = get_fred_api_value("T10BEI", fred_api_key)
    macro_md += f"| **D. 10年盈亏通胀率**<br>(T10BEI) | **{t10_val}%** | 通胀预期升温是硬资产上涨的核心推手。 | **中仓/重仓**: 突破前高利好 18 HKD，跌破2.0%观望。 |\n"

    # 5. TC/RCs 影子指标
    tc_data = get_tc_rc_proxy()
    macro_md += f"| **E. 铜矿加工费**<br>(TC Proxy) | {tc_data} | 矿企与冶炼厂利润博弈的命门。 | **做多铜矿**: TC跌破盈亏线，逻辑指向结构性缺矿。 |\n"

    # ================== 新增 4 大 FRED 核心指标 ==================

    # 6. 高收益债利差 (信用风险)
    hy_spread = get_fred_api_value("BAMLH0A0HYM2", fred_api_key)
    macro_md += f"| **F. 高收益债利差**<br>(信用风险警报) | **{hy_spread}%** | 企业违约风险的真实体现，比VIX更难操纵。 | **系统性风控**: 若突破5.0%且陡峭上升，无条件转观望。 |\n"

    # 7. 10Y-2Y 期限利差 (衰退风险)
    yield_curve = get_fred_api_value("T10Y2Y", fred_api_key)
    macro_md += f"| **G. 10Y-2Y 利差**<br>(衰退与周期定价) | **{yield_curve}%** | 倒挂(<0)表紧缩，倒挂解除瞬间通常为衰退兑现。 | **动态调整**: 倒挂解除时大幅削减顺周期仓位，增持现金。 |\n"

    # 8. 10年期实际利率 (黄金绝对锚)
    real_rate = get_fred_api_value("DFII10", fred_api_key)
    macro_md += f"| **H. 10年期实际利率**<br>(黄金唯一定价锚) | **{real_rate}%** | 实际利率 = 名义利率 - 盈亏平衡通胀率。 | **重仓**: 实际利率下行是做多 18 HKD 胜率最高的阶段。 |\n"

    # 9. 广义美元指数 (非美资产压舱石)
    dtwexbgs = get_fred_api_value("DTWEXBGS", fred_api_key)
    macro_md += f"| **I. 广义美元指数**<br>(贸易加权) | **{dtwexbgs}** | 比DXY更真实反映美元在全球贸易中的强弱。 | **轻仓非美**: 该指数走强，港股与人民币资产承受极大压值。 |\n"

    return macro_md + "\n---\n"
