import time
import requests
import feedparser
import re
import urllib.parse
import concurrent.futures
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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
    # 伪装成真实的 Chrome 浏览器
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.9"
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
    """【终极穿甲弹】：并发对冲请求 (Direct + Allorigins + Codetabs)"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.9"
    }

    def try_direct():
        try:
            res = rss_dedicated_session.get(url, headers=headers, timeout=4.0)
            res.raise_for_status()
            # 防御 Cloudflare 的真人验证页面
            if b"<title>Just a moment" not in res.content and b"Cloudflare" not in res.content:
                return res.content
        except: pass
        return None

    def try_allorigins():
        try:
            proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}"
            res = requests.get(proxy_url, timeout=4.0)
            if res.status_code == 200:
                data = res.json()
                if "contents" in data and data["contents"] and "<title>Just a moment" not in data["contents"]:
                    return data["contents"].encode('utf-8')
        except: pass
        return None

    def try_codetabs():
        try:
            proxy_url = f"https://api.codetabs.com/v1/proxy/?quest={url}"
            res = requests.get(proxy_url, timeout=4.0)
            if res.status_code == 200 and b"<title>Just a moment" not in res.content:
                return res.content
        except: pass
        return None

    # 开 3 个独立线程，像赛狗一样同时去抢数据
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(try_direct),
            executor.submit(try_allorigins),
            executor.submit(try_codetabs)
        ]
        # 谁第一个拿到数据，就立刻返回谁，抛弃另外两个
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
        # 大模型卡壳时秒退英文
        return [t.replace('|', '-') for t in titles]

def process_single_site(category, site_info, api_key):
    site_name = site_info["site"]
    keywords = site_info["keywords"]
    url = site_info["url"]

    # 替换原本的 shared_session 抓取逻辑，启用抗封锁神器
    content = fetch_rss_content(url)

    if not content:
        return f"| **{category}** | {site_name} | *{keywords}* | [抓取超时或IP被拦截] |\n"

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
    max_threads = min(50, task_count) if task_count > 0 else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(process_single_site, cat, info, api_key) for cat, info in tasks]

        for future in futures:
            results.append(future.result())

    for r in results:
        md_content += r

    return md_content
