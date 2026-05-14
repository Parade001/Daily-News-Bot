import time
import requests
import feedparser
import re
import concurrent.futures
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from http_client import shared_session

# 【极致提速】：阉割大模型的重试执念，遇到 429 拥堵直接快速失败 (Fail-Fast)
def create_deepseek_session():
    session = requests.Session()
    retries = Retry(total=0, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries)
    session.mount('https://', adapter)
    return session

deepseek_session = create_deepseek_session()

# 【防拦截核心修复】：为 RSS 配置百兆并发池，并伪装成真实浏览器！
def create_rss_session():
    session = requests.Session()
    # 核心修复：华盛顿邮报、AI News 等外媒有很强的 Cloudflare 反爬墙
    # 必须加上真实的 User-Agent 和 Accept 头，否则 Python 默认请求会被瞬间 403 阻断！
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*;q=0.9"
    })
    retries = Retry(total=0) # 坚决不重试
    adapter = HTTPAdapter(pool_connections=100, pool_maxsize=100, max_retries=retries)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

rss_dedicated_session = create_rss_session()


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
        # 翻译 3 句话最多给 6 秒，不拖累主线程
        response = deepseek_session.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=6.0)
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
        # 只要超时、被 429 限流、报错，瞬间返回英文原文
        return [t.replace('|', '-') for t in titles]


def process_single_site(category, site_info, api_key):
    site_name = site_info["site"]
    keywords = site_info["keywords"]
    url = site_info["url"]

    try:
        # 使用带伪装头的专属 session，超时设为 5 秒
        res = rss_dedicated_session.get(url, timeout=5.0)
        res.raise_for_status() # 如果遇到 403、404 等错误，直接抛出异常跳入 except

        feed = feedparser.parse(res.content)

        if not feed.entries:
            return f"| **{category}** | {site_name} | *{keywords}* | [暂无更新或被反爬墙拦截] |\n"

        entries = feed.entries[:3]
        original_titles = [getattr(e, 'title', '无标题') for e in entries]
        links = [getattr(e, 'link', '#') for e in entries]

        # 尝试调用翻译
        zh_titles = batch_translate_deepseek(original_titles, api_key)

        news_links_html = ""
        for zh_title, link in zip(zh_titles, links):
            news_links_html += f"• [{zh_title}]({link})<br><br>"

        return f"| **{category}** | {site_name} | *{keywords}* | {news_links_html} |\n"
    except Exception as e:
        return f"| **{category}** | {site_name} | *{keywords}* | [抓取超时或数据解析异常] |\n"


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
