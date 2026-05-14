import time
import requests
import feedparser
import re
import urllib.parse
import concurrent.futures
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ================== 会话池配置 (多重身份伪装) ==================

def create_deepseek_session():
    session = requests.Session()
    # 坚决不重试，遇到拥堵直接快速失败，降级输出英文
    retries = Retry(total=0)
    adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries)
    session.mount('https://', adapter)
    return session

def create_chrome_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.9"
    })
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=Retry(total=0))
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

def create_googlebot_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.9",
        "X-Forwarded-For": "66.249.66.1"
    })
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=Retry(total=0))
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

deepseek_session = create_deepseek_session()
chrome_session = create_chrome_session()
googlebot_session = create_googlebot_session()

# ================== 核心抓取与翻译 ==================

def fetch_rss_content(url):
    """【全天候穿甲弹】：多面具身份伪装 + 全通道跳板并发对冲"""

    def is_valid_xml(content_bytes):
        if not content_bytes: return False
        content_lower = content_bytes.lower()
        if b"<rss" in content_lower or b"<feed" in content_lower or b"<channel" in content_lower:
            if b"just a moment" in content_lower or b"are you a robot" in content_lower or b"security check" in content_lower:
                return False
            return True
        return False

    def try_chrome():
        try:
            res = chrome_session.get(url, timeout=4.5)
            if res.status_code == 200 and is_valid_xml(res.content): return res.content
        except: pass
        return None

    def try_googlebot():
        try:
            res = googlebot_session.get(url, timeout=4.5)
            if res.status_code == 200 and is_valid_xml(res.content): return res.content
        except: pass
        return None

    def try_allorigins():
        try:
            proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}"
            res = chrome_session.get(proxy_url, timeout=4.5)
            if res.status_code == 200:
                data = res.json()
                if "contents" in data and data["contents"]:
                    content_bytes = data["contents"].encode('utf-8')
                    if is_valid_xml(content_bytes): return content_bytes
        except: pass
        return None

    def try_rss2json():
        try:
            proxy_url = f"https://api.rss2json.com/v1/api.json?rss_url={urllib.parse.quote(url)}"
            res = chrome_session.get(proxy_url, timeout=4.5)
            if res.status_code == 200:
                data = res.json()
                if data.get("status") == "ok":
                    xml_str = '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
                    for item in data.get("items", [])[:3]:
                        title = item.get('title', '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        link = item.get('link', '').replace('&', '&amp;')
                        xml_str += f"<item><title>{title}</title><link>{link}</link></item>"
                    xml_str += "</channel></rss>"
                    return xml_str.encode('utf-8')
        except: pass
        return None

    # 开 4 个不同身份/通道的独立线程，进行极限竞速
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(try_chrome),
            executor.submit(try_googlebot),
            executor.submit(try_allorigins),
            executor.submit(try_rss2json)
        ]
        # 谁最先骗过防火墙拿到真实数据，就返回给主程序
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

    content = fetch_rss_content(url)

    if not content:
        # 4路人马全军覆没时才会报错
        return f"| **{category}** | {site_name} | *{keywords}* | [防爬虫强力拦截或抓取超时] |\n"

    try:
        feed = feedparser.parse(content)

        if not feed.entries:
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
    # 动态分配线程，一波流
    max_threads = min(50, task_count) if task_count > 0 else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(process_single_site, cat, info, api_key) for cat, info in tasks]

        for future in futures:
            results.append(future.result())

    for r in results:
        md_content += r

    return md_content
