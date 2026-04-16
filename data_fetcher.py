import re
import time
import urllib.parse
import feedparser
import concurrent.futures
from http_client import shared_session

def fetch_with_retry(url, is_json=False, max_retries=2, timeout=4.0):
    for i in range(max_retries):
        try:
            r = shared_session.get(url, timeout=timeout)
            if r.status_code == 200: return r.json() if is_json else r.text
        except Exception: pass
    return None

def fetch_html_concurrently(url):
    """【黑科技：并发对冲】同时向三个通道发射请求，谁先成功返回用谁，彻底消灭排队阻塞"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }

    def try_direct():
        try:
            r = shared_session.get(url, headers=headers, timeout=4.0)
            if r.status_code == 200 and "<title>Just a moment" not in r.text: return r.text
        except: pass
        return None

    def try_allorigins():
        try:
            r = shared_session.get(f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}", timeout=4.0)
            if r.status_code == 200:
                html = r.json().get("contents", "")
                if html and "<title>Just a moment" not in html: return html
        except: pass
        return None

    def try_codetabs():
        try:
            r = shared_session.get(f"https://api.codetabs.com/v1/proxy/?quest={url}", timeout=4.0)
            if r.status_code == 200 and "<title>Just a moment" not in r.text: return r.text
        except: pass
        return None

    # 开 3 个独立线程同时去抢数据
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(try_direct), executor.submit(try_allorigins), executor.submit(try_codetabs)]
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res: return res
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
        r = shared_session.get(url, timeout=4.0)
        if r.status_code == 200:
            res = r.json().get('quoteResponse', {}).get('result', [])
            if res: return res[0].get('regularMarketPrice')
    except: pass
    return None

def get_lme_spread():
    url = "https://www.westmetall.com/en/markdaten.php"
    html = fetch_html_concurrently(url)
    if html:
        try:
            match = re.search(r'Copper\s*</a>.*?<a[^>]*>\s*([\d,\.]+)\s*</a>.*?<a[^>]*>\s*([\d,\.]+)\s*</a>', html, re.IGNORECASE | re.DOTALL)
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
    """【极限竞速】中银香港直连与雅虎兜底同时发射，谁快用谁"""
    def fetch_boc():
        html = fetch_html_concurrently("https://www.bochk.com/whk/rates/cnyHiborRates/cnyHiborRates-enquiry.action?lang=cn")
        if html:
            on_match = re.search(r'(?:Overnight|隔夜)[^\d]*?([\d\.]+)\s*%?', html, re.IGNORECASE)
            if on_match: return float(on_match.group(1)), "隔夜(BOC)"
        return None

    # 开 3 个线程，让中银、雅虎瞬时、雅虎历史同时去抢
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        fut_boc = executor.submit(fetch_boc)
        fut_yq = executor.submit(get_yahoo_quote, "CNHON=X")
        fut_yh = executor.submit(get_yahoo_history, "CNHON=X")

        # 最高优先级：中银香港 (等待最多4秒)
        boc_res = fut_boc.result()
        if boc_res: return boc_res

        # 降级：雅虎瞬时报价
        yq_res = fut_yq.result()
        if yq_res: return yq_res, "隔夜(YQ)"

        # 终极兜底：雅虎历史
        yh_res = fut_yh.result()
        if yh_res and yh_res[0]: return yh_res[0], "隔夜(YH)"

    return None, "全断流"
