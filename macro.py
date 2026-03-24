import re
import urllib.parse
import feedparser
import time
from http_client import shared_session

def fetch_with_fallback(url):
    """【强化】多重跳板，增加对 None 的容错处理"""
    try:
        r = shared_session.get(url, timeout=10)
        if r.status_code == 200 and "Cloudflare" not in r.text: return r.text
    except: pass

    # 跳板 1
    try:
        r = shared_session.get(f"https://api.allorigins.win/raw?url={urllib.parse.quote(url)}", timeout=15)
        if r.status_code == 200: return r.text
    except: pass

    return "" # 返回空字符串而非 None，防止后续 .search() 崩溃

def get_fred_api_value(series_id, api_key):
    """【强化】自动处理数据回溯，跳过节假日点号"""
    if not api_key: return "未配置Key"
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json&sort_order=desc&limit=5"
    try:
        r = shared_session.get(url, timeout=10)
        if r.status_code == 200:
            obs = r.json().get('observations', [])
            for item in obs:
                val = item.get('value', '.')
                if val not in ['.', '', 'NaN', None]: return val
    except: pass
    return "API暂无数据"

def get_cips_structural_data():
    """【修复】增加 HIBOR 抓取的异常保护"""
    hibor = "报价延迟"
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/CNHON=X?interval=1d&range=1d"
        r = shared_session.get(url, timeout=10).json()
        val = r['chart']['result'][0]['meta']['regularMarketPrice']
        hibor = f"{val:.2f}%"
    except: pass # 即使 Yahoo 挂了，也不影响后续执行

    structural_news = "[月度报告尚未更新]"
    try:
        # 尝试从多个宏观新闻源扫描 CIPS 关键词
        feed = feedparser.parse("https://www.scmp.com/rss/91/feed")
        for entry in feed.entries[:10]:
            text = (entry.title + " " + getattr(entry, 'description', '')).upper()
            if "CIPS" in text:
                vol = re.search(r'(\d+(?:\.\d+)?)\s*(?:TRILLION|BILLION)\s*YUAN', text)
                if vol:
                    structural_news = f"最新月度规模: **{vol.group(0).lower()}**"
                    break
    except: pass

    return f"**离岸利率(HIBOR)**: {hibor}<br>**结构快照**: {structural_news}"

def get_westmetall_spread():
    """【修复】增加对 html 为空的预检查"""
    url = "https://www.westmetall.com/en/markdaten.php?action=show_table&field=LME_Cu_cash"
    html = fetch_with_fallback(url)

    # 核心防御：如果 html 为空直接返回，不执行正则
    if not html or '3-months' not in html:
        return "解析失败 (WAF拦截)", "无法判断"

    try:
        rows = re.findall(r'<tr>(.*?)</tr>', html, re.DOTALL)
        for row in rows:
            cols = re.findall(r'<td>(.*?)</td>', row, re.DOTALL)
            if len(cols) >= 3:
                date_str = cols[0].strip()
                cash = float(re.sub(r'[^0-9\.\-]', '', cols[1].replace(',', '')))
                m3 = float(re.sub(r'[^0-9\.\-]', '', cols[2].replace(',', '')))
                spread = cash - m3
                struct = "🔴 现货溢价" if spread > 0 else "🟢 期货溢价"
                return f"Cash: ${cash:.0f}<br>3M: ${m3:.0f}<br>价差: **${spread:.2f}**<br>{struct}", f"更新日: {date_str}"
    except: pass
    return "数据格式异常", "无法解析"

def get_tc_rc_proxy():
    """影子指标防御"""
    try:
        fcx = shared_session.get("https://query1.finance.yahoo.com/v8/finance/chart/FCX?interval=1d&range=1d").json()['chart']['result'][0]['meta']['regularMarketPrice']
        jiangxi = shared_session.get("https://query1.finance.yahoo.com/v8/finance/chart/0358.HK?interval=1d&range=1d").json()['chart']['result'][0]['meta']['regularMarketPrice']
        ratio = fcx / (jiangxi / 7.8)
        ratio_str = f"矿冶比: **{ratio:.2f}**"
    except: ratio_str = "股价接口异常"

    return f"{ratio_str}<br>[近日无TC报价新闻]"

def fetch_macro_indicators(fred_api_key=None):
    """组装 Markdown 表格"""
    macro_md = "## 📈 核心宏观全景面板 (10大领先指标)\n\n"
    macro_md += "| 变量名称 | 最新状态/数据 | 核心逻辑与决策映射 | 状态解读 |\n"
    macro_md += "| :--- | :--- | :--- | :--- |\n"

    # A. 铜升贴水
    a_val, a_adv = get_westmetall_spread()
    macro_md += f"| **A. LME铜升贴水** | {a_val} | 物理库存的风向标。 | {a_adv} |\n"

    # B. RRP 逆回购
    rrp = get_fred_api_value("RRPONTSYD", fred_api_key)
    macro_md += f"| **B. 逆回购余额** | **{rrp}** (B) | 余额下行 = 市场放水。 | 保持做多 VOO |\n"

    # D. 盈亏通胀率
    t10 = get_fred_api_value("T10BEI", fred_api_key)
    macro_md += f"| **D. 10年盈亏通胀率** | **{t10}%** | 利多 18 HKD。 | 突破前高重仓黄金 |\n"

    # F. CIPS 综合指标
    cips_data = get_cips_structural_data()
    macro_md += f"| **F. CIPS/跨境流动性** | {cips_data} | 监控离岸抽水压力。 | 利率暴涨说明紧缩 |\n"

    # 其他指标使用回溯算法获取
    hy = get_fred_api_value("BAMLH0A0HYM2", fred_api_key)
    macro_md += f"| **G. 高收益债利差** | **{hy}%** | 信用警报指标。 | 突破5.0%减仓风险资产 |\n"

    yc = get_fred_api_value("T10Y2Y", fred_api_key)
    macro_md += f"| **H. 10Y-2Y 利差** | **{yc}%** | 倒挂解除预示衰退。 | 倒挂解除瞬间增持现金 |\n"

    rr = get_fred_api_value("DFII10", fred_api_key)
    macro_md += f"| **I. 10年实际利率** | **{rr}%** | 黄金绝对反向指标。 | 实际利率下行重仓黄金 |\n"

    usd = get_fred_api_value("DTWEXBGS", fred_api_key)
    macro_md += f"| **J. 广义美元指数** | **{usd}** | 美元全球贸易强弱。 | 指数走强利空港股 |\n"

    # E. TC 加工费
    tc_data = get_tc_rc_proxy()
    macro_md += f"| **E. 铜矿加工费** | {tc_data} | 逻辑指向结构性缺矿。 | TC跌破20美元利多COPX |\n"

    return macro_md + "\n---\n"
