import time
import requests
import feedparser
from http_client import shared_session

def translate_with_deepseek(text, api_key):
    if not text: return "无标题"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的国际政经翻译。请将输入的新闻标题翻译为地道的简体中文。要求：1. 严禁换行；2. 严禁摘要；3. 直接输出翻译。"},
            {"role": "user", "content": text}
        ],
        "temperature": 0.1
    }
    try:
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
        result = response.json()['choices'][0]['message']['content'].strip()
        return result.replace('\n', ' ').replace('\r', ' ').replace('|', '-')
    except:
        return text.replace('|', '-')

def fetch_rss_news(rss_config, api_key):
    md_content = "## 📰 核心政经与大宗商品速递\n\n"
    md_content += "| 分类 | 网站 (中英文) | 详细关键词与分类 | 最新中文标题与原文链接 |\n"
    md_content += "| :--- | :--- | :--- | :--- |\n"

    total_sites = sum(len(sites) for sites in rss_config.values())
    current_site = 0

    for category, sites in rss_config.items():
        for site_info in sites:
            current_site += 1
            site_name = site_info["site"]
            keywords = site_info["keywords"]
            url = site_info["url"]

            print(f"[{current_site}/{total_sites}] 抓取资讯: {site_name}")
            try:
                res = shared_session.get(url, timeout=15)
                feed = feedparser.parse(res.content)

                if not feed.entries:
                    md_content += f"| **{category}** | {site_name} | *{keywords}* | [暂无更新或解析失败] |\n"
                    continue

                news_links_html = ""
                for entry in feed.entries[:3]:
                    original_title = getattr(entry, 'title', '无标题')
                    link = getattr(entry, 'link', '#')
                    zh_title = translate_with_deepseek(original_title, api_key)
                    news_links_html += f"• [{zh_title}]({link})<br><br>"

                md_content += f"| **{category}** | {site_name} | *{keywords}* | {news_links_html} |\n"
                time.sleep(1)
            except Exception as e:
                md_content += f"| **{category}** | {site_name} | *{keywords}* | [数据解析异常] |\n"

    return md_content
