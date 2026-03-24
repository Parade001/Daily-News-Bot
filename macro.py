import re
import feedparser
from http_client import shared_session

def get_yahoo_price(ticker):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    try:
        r = shared_session.get(url, timeout=10)
        return r.json()['chart']['result'][0]['meta']['regularMarketPrice']
    except: return None

def get_fred_value(series_id):
    url = f"https://fred.stlouisfed.org/series/{series_id}"
    try:
        r = shared_session.get(url, timeout=10)
        match = re.search(r'class="series-meta-observation-value">([^<]+)</span>', r.text)
        return match.group(1).strip() if match else "解析失败"
    except: return "超时"

def get_westmetall_spread():
    url = "https://www.westmetall.com/en/markdaten.php?action=show_table&field=LME_Cu_cash"
    try:
        r = shared_session.get(url, timeout=15)
        match = re.search(r'<tr>\s*<td>([^<]+)</td>\s*<td>([\d\.,]+)</td>\s*<td>([\d\.,]+)</td>', r.text)
        if match:
            date_str = match.group(1).strip()
            cash = float(match.group(2).replace(',', ''))
            m3 = float(match.group(3).replace(',', ''))
            spread = cash - m3
            struct = "🔴 现货溢价 (Backwardation)" if spread > 0 else "🟢 期货溢价 (Contango)"
            adv = "库存短缺, 逼空支撑强" if spread > 0 else "库存充裕, 结构偏空/中性"
            return f"Cash: ${cash}<br>3M: ${m3}<br>价差: **${spread:.2f}**<br>{struct}<br>*(更新日: {date_str})*", adv
        return "数据节点解析失败", "无法判断"
    except: return "抓取超时", "网络异常"

def get_tc_rc_proxy():
    fcx = get_yahoo_price("FCX")
    jiangxi = get_yahoo_price("0358.HK")
    ratio_str = "[股价接口超时]"
    if fcx and jiangxi:
        ratio = fcx / (jiangxi / 7.8)
        ratio_str = f"矿冶比值 (FCX/江铜): **{ratio:.2f}**<br>*(↑矿端强势, ↓冶炼强势)*"

    tc_news = "[近日新闻未命中 TC 数值]"
    try:
        feed = feedparser.parse("https://www.mining.com/commodity/copper/feed/")
        for entry in feed.entries[:15]:
            text = entry.title + " " + getattr(entry, 'description', '')
            matches = re.findall(r'(?:TCs?|treatment charges?).*?\$?(\d+(?:\.\d+)?)\s*(?:\/|per)?\s*(?:ton|tonne)', text, re.IGNORECASE)
            if matches:
                vals = [float(m) for m in matches if 5 < float(m) < 150]
                if vals:
                    tc_news = f"最近新闻提取 TC: **${vals[0]}/ton**<br>*(信源: Mining.com)*"
                    break
    except: tc_news = "[RSS源抓取异常]"
    return f"{ratio_str}<br><br>{tc_news}"

def fetch_macro_indicators():
    macro_md = "## 📈 核心补充：盯盘软件“看不见”的五个关键变量\n\n"
    macro_md += "| 变量名称 | 最新状态/数值 | 核心运转逻辑 | 观测源 | 宏观映射与决策 |\n"
    macro_md += "| :--- | :--- | :--- | :--- | :--- |\n"

    spread_data, spread_adv = get_westmetall_spread()
    macro_md += f"| **A. 铜现货升贴水** | {spread_data} | 现货贵于期货说明物理库存极度短缺。 | Westmetall | {spread_adv} |\n"

    rrp_val = get_fred_value("RRPONTSYD")
    macro_md += f"| **B. 逆回购余额** | **{rrp_val}** (B) | 余额下行说明流动性正释放至市场。 | FRED API | 保持做多 VOO/COPX。 |\n"

    cnh = get_yahoo_price("USDCNH=X")
    cny = get_yahoo_price("USDCNY=X")
    spread_str = f"离岸: {cnh:.4f}<br>在岸: {cny:.4f}<br>价差: **{(cnh - cny) * 10000:.0f} pips**" if cnh and cny else "接口异常"
    macro_md += f"| **C. CNH-CNY 价差** | {spread_str} | CNH反映国际资金真实情绪。 | Yahoo | 价差扩大需警惕资金外逃。 |\n"

    t10_val = get_fred_value("T10BEI")
    macro_md += f"| **D. 盈亏通胀率** | **{t10_val}%** | 通胀预期是金价上涨的核心推手。 | FRED API | 突破前高利好 18 HKD。 |\n"

    tc_data = get_tc_rc_proxy()
    macro_md += f"| **E. 铜矿加工费** | {tc_data} | TC跌破盈亏线即支撑铜长期价格。 | Yahoo/Mining | 逻辑指向结构性缺矿。 |\n"

    return macro_md + "\n---\n"
