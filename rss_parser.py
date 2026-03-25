import time
import requests
import feedparser
import re
import concurrent.futures
from http_client import shared_session

# 全局复用 DeepSeek 的 HTTP Session，减少底层的 TLS 握手耗时
deepseek_session = requests.Session()

def batch_translate_deepseek(titles, api_key):
    """【优化 2】批量翻译：将多个标题打包成 1 次 API 请求，大幅压缩耗时"""
    if not titles: return []

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # 组装带序号的翻译长文 (如: 0. Title 1 \n 1. Title 2)
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
        # 发起单次批量请求
        response = deepseek_session.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
        content = response.json()['choices'][0]['message']['content'].strip()

        # 鲁棒性正则解析：精准还原每一行翻译对应的原文位置
        translated_dict = {}
        for line in content.split('\n'):
            match = re.match(r'^(\d+)\.\s*(.*)', line.strip())
            if match:
                idx = int(match.group(1))
                translated_dict[idx] = match.group(2).replace('|', '-').replace('\n', ' ')

        # 组装返回列表，若模型漏翻则使用英文原文兜底
        result = []
        for i in range(len(titles)):
            result.append(translated_dict.get(i, titles[i].replace('|', '-')))
        return result
    except Exception as e:
        # 极端情况回退为原文
        return [t.replace('|', '-') for t in titles]

def process_single_site(category, site_info, api_key):
    """处理单个网站的抓取与翻译任务（用于放进线程池执行）"""
    site_name = site_info["site"]
    keywords = site_info["keywords"]
    url = site_info["url"]

    try:
        res = shared_session.get(url, timeout=15)
        feed = feedparser.parse(res.content)

        if not feed.entries:
            return f"| **{category}** | {site_name} | *{keywords}* | [暂无更新或解析失败] |\n"

        # 提取前 3 条标题和链接
        entries = feed.entries[:3]
        original_titles = [getattr(e, 'title', '无标题') for e in entries]
        links = [getattr(e, 'link', '#') for e in entries]

        # 调用批量翻译函数
        zh_titles = batch_translate_deepseek(original_titles, api_key)

        # 组装单行的 Markdown
        news_links_html = ""
        for zh_title, link in zip(zh_titles, links):
            news_links_html += f"• [{zh_title}]({link})<br><br>"

        return f"| **{category}** | {site_name} | *{keywords}* | {news_links_html} |\n"
    except Exception as e:
        return f"| **{category}** | {site_name} | *{keywords}* | [数据解析异常] |\n"

def fetch_rss_news(rss_config, api_key):
    """【优化 1】多线程并发驱动引擎"""
    md_content = "## 📰 核心政经与大宗商品速递\n\n"
    md_content += "| 分类 | 网站 (中英文) | 详细关键词与分类 | 最新中文标题与原文链接 |\n"
    md_content += "| :--- | :--- | :--- | :--- |\n"

    # 将嵌套字典展平为线性任务列表
    tasks = []
    for category, sites in rss_config.items():
        for site_info in sites:
            tasks.append((category, site_info))

    print(f"📡 RSS 模块：准备并发抓取与翻译 {len(tasks)} 个源...")

    # 启动 10 个工人的并发线程池
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # submit 会立刻将所有任务并行发射出去，极速执行
        futures = [executor.submit(process_single_site, cat, info, api_key) for cat, info in tasks]

        # 按照原来的先后顺序提取结果，保证表格顺序不乱
        for future in futures:
            results.append(future.result())

    # 汇总 Markdown 结果
    for r in results:
        md_content += r

    return md_content
