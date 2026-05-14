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
    """【反爬虫终极利器】：直连 + 跳板双重绕过"""
    # 1. 尝试伪装浏览器直连 (4秒)
    try:
        res = rss_dedicated_session.get(url, timeout=4.0)
        res.raise_for_status()
        return res.content
    except Exception:
        pass

    # 2. 如果 GitHub Actions 的云端 IP 被华盛顿邮报拉黑，动用 Allorigins 代理跳板 (4秒)
    try:
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}"
        # 这里用普通的 requests 发送，避免复杂的 headers 反而干扰代理服务器
        res = requests.get(proxy_url, timeout=4.0)
        if res.status_code == 200:
            data = res.json()
            if "contents" in data and data["contents"]:
                return data["contents"].encode('utf-8')
    except Exception:
        pass

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
