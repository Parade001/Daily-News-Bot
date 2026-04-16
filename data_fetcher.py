import re
import time
import urllib.parse
import feedparser
from http_client import shared_session

def fetch_with_retry(url, is_json=False, max_retries=3):
    for i in range(max_retries):
        try:
            # 【提速核心】强制 5 秒超时，绝不给慢节点挂起线程的机会
            r = shared_session.get(url, timeout=5)
            if r.status_code == 200: return r.json() if is_json else r.text
        except Exception: time.sleep(2 ** i)
    return None

def fetch_html_with_fallback(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.google.com/"
    }
    try:
        r = shared_session.get(url, headers=headers, timeout=5) # 5秒
        if r.status_code == 200 and "<title>Just a moment" not in r.text: return r.text
    except: pass
    try:
        r = shared_session.get(f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}", timeout=5) # 5秒
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

def get_lme_spread():
    url = "https://www.westmetall.com/en/markdaten.php"
    html = fetch_html_with_fallback(url)
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
