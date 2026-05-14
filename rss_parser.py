import time
import requests
import feedparser
import re
import urllib.parse
import concurrent.futures
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from http_client import shared_session

# ================== 会话池配置 ==================

def create_deepseek_session():
    session = requests.Session()
    # 坚决不重试，遇到拥堵直接快速失败，降级输出英文
    retries = Retry(total=0)
    adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries)
    session.mount('https://', adapter)
    return session

def create_rss_session():
    session = requests.Session()
    # 【终极欺骗】：不装普通 Chrome 浏览器了，我们装作 Google 搜索引擎的爬虫！
    # 新闻网站为了 SEO 流量，防火墙绝对不敢拦截 Googlebot。
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.9",
        "X-Forwarded-For": "66.249.66.1"  # 伪造 Google 爬虫的专用 IP 段
    })
    retries = Retry(total=0)
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

deepseek_session = create_deepseek_session()
rss_dedicated_session = create_rss_session()

# ================== 核心抓取与翻译 ==================

def fetch_rss_content(url):
    """【反爬虫终极利器】：4 路并发对冲 + 严格剔除防爬虫假网页"""

    # 过滤器：严格验证是否为真实的新闻 XML，防止把防爬虫 HTML 当成新闻解析
    def is_valid_xml(content_bytes):
        if not content_bytes: return False
        content_lower = content_bytes.lower()
        # 必须包含 RSS 或 Atom 的核心标签
        if b"<rss" in content_lower or b"<feed" in content_lower or b"<channel" in content_lower:
            # 且不能包含常见的防爬虫特征 (Cloudflare, PerimeterX, 等)
            if b"just a moment" in content_lower or b"are you a robot" in content_lower or b"security check" in content_lower:
                return False
            return True
        return False

    def try_direct():
        try:
            res = rss_dedicated_session.get(url, timeout=4.5)
            if res.status_code == 200 and is_valid_xml(res.content):
                return res.content
        except: pass
        return None

    def try_allorigins():
        try:
            proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}"
            res = requests.get(proxy_url, timeout=4.5)
            if res.status_code == 200:
                data = res.json()
                if "contents" in data and data["contents"]:
                    content_bytes = data["contents"].encode('utf-8')
                    if is_valid_xml(content_bytes): return content_bytes
        except: pass
        return None

    def try_codetabs():
        try:
            proxy_url = f"https://api.codetabs.com/v1/proxy/?quest={url}"
            res = requests.get(proxy_url, timeout=4.5)
            if res.status_code == 200 and is_valid_xml(res.content):
                return res.content
        except: pass
        return None

    def try_corsproxy():
        try:
            proxy_url = f"https://corsproxy.io/?url={urllib.parse.quote(url)}"
            res = requests.get(proxy_url, timeout=4.5)
            if res.status_code == 200 and is_valid_xml(res.content):
                return res.content
        except: pass
        return None

    # 开 4 个独立线程，像赛狗一样同时去抢同一份数据
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(try_direct),
            executor.submit(try_allorigins),
            executor.submit(try_codetabs),
            executor.submit(try_corsproxy)
        ]
        # 谁第一个拿到真实的 XML 数据，立刻返回
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                return res

    return None

def batch_translate_deepseek(titles, api_key):
    if not titles: return []

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    input_text = "\n".join([f"{i}. {t}" for i, t in enumerate(titles)])

    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的国际政经翻译。请将输入的编号列表逐句翻译为简体中文。要求：\n1. 严格保留原有的序号(如 0. 1. 2.)格式；\n2. 严禁换行和摘要；\n3. 直接输出翻译结果，禁止包含任何说明或解释文字。"},
            {"role": "user", "content": input_text}
        ],
        "temperature": 0.1
    }

    try:
        # 大模型翻译时限锁定 8 秒
        response = deepseek_session.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=8.0)
        response.raise_for_status()
        content = response.json()['choices'][0]['message']['content'].strip()

        translated_dict = {}
        for line in content.split('\n'):
            match = re.match(r'^(\d+)\.\s*(.*)', line.strip())
            if match:
                idx = int(match.group(1))
                translated_dict[idx] = match.group(2).replace('|', '-').replace('\n', ' ')

        result = []
        for i in range(len(titles)):
            result.append(translated_dict.get(i, titles[i].replace('|', '-')))
        return result
    except Exception as e:
        return [t.replace('|', '-') for t in titles]

def process_single_site(category, site_info, api_key):
    site_name = site_info["site"]
    keywords = site_info["keywords"]
    url = site_info["url"]

    # 启用抗封锁并发引擎
    content = fetch_rss_content(url)

    if not content:
        # 只有在直连和3个跳板全军覆没、或者抓到假网页时，才会走到这里
        return f"| **{category}** | {site_name} | *{keywords}* | [防爬虫强力拦截或抓取超时] |\n"

    try:
        feed = feedparser.parse(content)

        if not feed.entries:
            # 走到这里，说明是真 XML，但真的没发新闻
            return f"| **{category}** | {site_name} | *{keywords}* | [暂无更新] |\n"

        entries = feed.entries[:3]
        original_titles = [getattr(e, 'title', '无标题') for e in entries]
        links = [getattr(e, 'link', '#') for e in entries]

        # 调用翻译
        zh_titles = batch_translate_deepseek(original_titles, api_key)

        news_links_html = ""
        for zh_title, link in zip(zh_titles, links):
            news_links_html += f"• [{zh_title}]({link})<br><br>"

        return f"| **{category}** | {site_name} | *{keywords}* | {news_links_html} |\n"
    except Exception as e:
        return f"| **{category}** | {site_name} | *{keywords}* | [数据解析异常] |\n"

def fetch_rss_news(rss_config, api_key):
    md_content = "## 📰 核心政经与大宗商品速递\n\n"
    md_content += "| 分类 | 网站 (中英文) | 详细关键词与分类 | 最新中文标题与原文链接 |\n"
    md_content += "| :--- | :--- | :--- | :--- |\n"

    tasks = []
    for category, sites in rss_config.items():
        for site_info in sites:
            tasks.append((category, site_info))

    task_count = len(tasks)
    print(f"📡 RSS 模块：准备并发抓取与翻译 {task_count} 个源...")

    results = []
    # 动态分配线程，最高允许 50 个并发（一波流）
    max_threads = min(50, task_count) if task_count > 0 else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(process_single_site, cat, info, api_key) for cat, info in tasks]

        for future in futures:
            results.append(future.result())

    for r in results:
        md_content += r

    return md_content
