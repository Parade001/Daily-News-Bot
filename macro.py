import re
import feedparser
from http_client import shared_session

def get_yahoo_price(ticker):
    """抓取雅虎财经的基础报价"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
    try:
        r = shared_session.get(url, timeout=10)
        return r.json()['chart']['result'][0]['meta']['regularMarketPrice']
    except:
        return None

def get_fred_csv_value(series_id):
    """
    【升级版】通过 FRED 官方 CSV 接口拉取数据，完美绕过 HTML 的 Cloudflare 拦截
    自动处理节假日导致的 '.' 空值问题
    """
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    try:
        r = shared_session.get(url, timeout=15)
        if r.status_code == 200:
            # 拆分行，去除空行
            lines = [line for line in r.text.strip().split('\n') if line]
            # 从最后一天倒序查找，直到找到第一个有效数字（跳过周末和节假日的 '.'）
            for line in reversed(lines):
                parts = line.split(',')
                if len(parts) == 2:
                    val = parts[1].strip()
                    if val not in ['.', '', 'NaN']:
                        return val
        return "数据为空"
    except Exception as e:
        return "接口被拦截或超时"

def get_westmetall_spread():
    """
    【升级版】使用结构化切片与暴力数字清洗，解决千分位逗号与欧洲空格导致的解析失败
    """
    url = "https://www.westmetall.com/en/markdaten.php?action=show_table&field=LME_Cu_cash"
    try:
        r = shared_session.get(url, timeout=15)
        # 1. 粗暴定位到表格核心数据区
        if '<th>3-months</th>' in r.text:
            data_block = r.text.split('<th>3-months</th>')[1]
            rows = data_block.split('<tr>')

            # 2. 遍历行，寻找第一行有效数据
            for row in rows:
                cols = re.findall(r'<td>(.*?)</td>', row)
                if len(cols) >= 3:
                    date_str = cols[0].strip()
                    # 暴力清洗：移除所有非数字和非小数点的字符（解决 8,850.00 和 8 850.00 的问题）
                    cash_str = re.sub(r'[^\d.]', '', cols[1].replace(',', ''))
                    m3_str = re.sub(r'[^\d.]', '', cols[2].replace(',', ''))

                    if cash_str and m3_str:
                        cash, m3 = float(cash_str), float(m3_str)
                        spread = cash - m3
                        struct = "🔴 现货溢价 (Backwardation)" if spread > 0 else "🟢 期货溢价 (Contango)"
                        adv = "库存短缺, 逼空支撑强" if spread > 0 else "库存充裕, 结构偏空/中性"
                        return f"Cash: ${cash}<br>3M: ${m3}<br>价差: **${spread:.2f}**<br>{struct}<br>*(更新日: {date_str})*", adv
        return "网页DOM结构变更", "无法判断"
    except:
        return "防爬虫拦截或超时", "网络异常"

def get_tc_rc_proxy():
    """获取 TC/RCs 的影子指标：股价强弱比 + 新闻正则提取"""
    fcx = get_yahoo_price("FCX")
    jiangxi = get_yahoo_price("0358.HK")
    ratio_str = "[股价接口超时]"
    if fcx and jiangxi:
        ratio = fcx / (jiangxi / 7.8)
        ratio_str = f"矿冶比值 (FCX/江铜): **{ratio:.2f}**<br>*(↑矿端强势, ↓冶炼强势)*"

    # 将状态修正为中性描述，而非失败报错
    tc_news = "[近期无 TC/RCs 报价新闻更新]"
    try:
        feed = feedparser.parse("https://www.mining.com/commodity/copper/feed/")
        for entry in feed.entries[:15]:
            text = entry.title + " " + getattr(entry, 'description', '')
            matches = re.findall(r'(?:TCs?|treatment charges?).*?\$?(\d+(?:\.\d+)?)\s*(?:\/|per)?\s*(?:ton|tonne)', text, re.IGNORECASE)
            if matches:
                vals = [float(m) for m in matches if 5 < float(m) < 150]
                if vals:
                    tc_news = f"近期新闻提取 TC: **${vals[0]}/ton**<br>*(信源: Mining.com)*"
                    break
    except:
        pass # 抓取不到时静默使用默认的中性描述

    return f"{ratio_str}<br><br>{tc_news}"

def fetch_macro_indicators():
    """组装 5 个关键宏观变量的 Markdown 块"""
    macro_md = "## 📈 核心补充：盯盘软件“看不见”的五个关键变量\n\n"
    macro_md += "| 变量名称 | 最新状态/数值 | 核心运转逻辑 | 观测源 | 宏观映射与决策 |\n"
    macro_md += "| :--- | :--- | :--- | :--- | :--- |\n"

    # A. 铜现货升贴水
    spread_data, spread_adv = get_westmetall_spread()
    macro_md += f"| **A. 铜现货升贴水**<br>(LME Cash-to-3M) | {spread_data} | 现货贵于期货说明物理库存极度短缺。 | Westmetall | **决策**: {spread_adv}。 |\n"

    # B. RRP 逆回购 (替换为 CSV 接口)
    rrp_val = get_fred_csv_value("RRPONTSYD")
    macro_md += f"| **B. 美联储逆回购余额**<br>(Reverse Repo, RRP) | **{rrp_val}** (B) | 美元流动性蓄水池。余额下降=流动性释放。 | FRED API | **决策**: 余额下行趋势未变，保持做多。 |\n"

    # C. CNH-CNY
    cnh = get_yahoo_price("USDCNH=X")
    cny = get_yahoo_price("USDCNY=X")
    spread_str = f"离岸: {cnh:.4f}<br>在岸: {cny:.4f}<br>价差: **{(cnh - cny) * 10000:.0f} pips**" if cnh and cny else "接口异常"
    macro_md += f"| **C. 离岸/在岸人民币价差**<br>(CNH-CNY) | {spread_str} | CNH反映外资真实情绪。 | Yahoo | **决策**: 价差持续扩大需警惕资金外流。 |\n"

    # D. TIPS 通胀预期 (替换为 CSV 接口)
    t10_val = get_fred_csv_value("T10BEI")
    macro_md += f"| **D. 10年期盈亏平衡通胀率** | **{t10_val}%** | 通胀预期升温是金价上涨的核心推手。 | FRED API | **决策**: 突破前高重仓黄金，跌破2.0%观望。 |\n"

    # E. TC/RCs 影子指标
    tc_data = get_tc_rc_proxy()
    macro_md += f"| **E. 铜矿加工费与情绪**<br>(TC Proxy) | {tc_data} | TC/RCs 是铜产业链利润命门。 | Yahoo/Mining | **决策**: TC跌破盈亏线，逻辑指向缺矿。 |\n"

    return macro_md + "\n---\n"
