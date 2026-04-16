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
    # total=0：坚决不重试。如果遇到 429 排队，直接抛异常，走底层 fallback 输出英文
    retries = Retry(total=0, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50, max_retries=retries)
    session.mount('https://', adapter)
    return session

deepseek_session = create_deepseek_session()

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
        # 【极致提速】：翻译 3 句话最多给 8 秒，绝不允许拖累主线程
        response = deepseek_session.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=8)
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
        # 只要超时、被 429 限流、报错，瞬间返回英文原文，不浪费一毫秒
        return [t.replace('|', '-') for t in titles]

def process_single_site(category, site_info, api_key):
    site_name = site_info["site"]
    keywords = site_info["keywords"]
    url = site_info["url"]

    try:
        # 【极致提速】：获取 RSS 限制为 5 秒，装死直接跳过
        res = shared_session.get(url, timeout=5)
        feed = feedparser.parse(res.content)

        if not feed.entries:
            return f"| **{category}** | {site_name} | *{keywords}* | [暂无更新或解析失败] |\n"

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
    # 【性能解封】：直接根据任务量动态分配线程，最高允许 50 个并发（一波流全部发完！）
    max_threads = min(50, task_count) if task_count > 0 else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = [executor.submit(process_single_site, cat, info, api_key) for cat, info in tasks]

        for future in futures:
            results.append(future.result())

    for r in results:
        md_content += r

    return md_content
