import feedparser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import datetime
import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import markdown  # 新增：用于将 Markdown 转换为精美的网页格式邮件

# ================== 核心配置区 ==================

SENDER_EMAIL = "xiongteng.red@gmail.com"
APP_PASSWORD = "kgyy init rmwf zckw" # 请确保这是有效的应用专用密码
RECEIVER_EMAIL = "xiongteng.red@gmail.com"
DEEPSEEK_API_KEY = "sk-b7f366f8e514436e8ce9c44f1a654845"

# 代理配置
PROXY_URL = "http://127.0.0.1:7897"
proxies = {
    'http': PROXY_URL,
    'https': PROXY_URL
}

# 工业级网络 Session 初始化
http_session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[ 500, 502, 503, 504 ])
adapter = HTTPAdapter(max_retries=retries)
http_session.mount('http://', adapter)
http_session.mount('https://', adapter)
http_session.proxies = proxies

# ================== 完整 28 个 RSS 源 ==================
RSS_SOURCES = {
    "国际/美国主流媒体": [
        {"site": "The New York Times (纽约时报)", "keywords": "美国政治, 国际关系", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"},
        {"site": "The Washington Post (华盛顿邮报)", "keywords": "华盛顿内幕, 全球视野", "url": "https://feeds.washingtonpost.com/rss/world"},
        {"site": "CNN", "keywords": "突发新闻, 地缘冲突", "url": "http://rss.cnn.com/rss/edition_world.rss"},
        {"site": "Fox News (福克斯新闻)", "keywords": "保守派视角, 美国内政", "url": "http://feeds.foxnews.com/foxnews/world"},
        {"site": "Los Angeles Times (洛杉矶时报)", "keywords": "美国西海岸, 亚太焦点", "url": "https://www.latimes.com/world/rss2.0.xml"},
    ],
    "商业/财经": [
        {"site": "Bloomberg (彭博社)", "keywords": "大宗商品, 贵金属, 美联储", "url": "https://feeds.bloomberg.com/markets/news.rss"},
        {"site": "The Wall Street Journal (华尔街日报)", "keywords": "美股大盘, 公司财报", "url": "https://feeds.a.dj.com/rss/RSSWSJ.xml"},
        {"site": "Forbes (福布斯)", "keywords": "财富管理, 商业领袖", "url": "https://www.forbes.com/business/feed/"},
        {"site": "Harvard Business Review", "keywords": "商业管理, 战略分析", "url": "https://feeds.hbr.org/harvardbusiness"},
        {"site": "Barron’s (巴伦周刊)", "keywords": "投资策略, 基金动向", "url": "https://www.barrons.com/rss"},
        {"site": "MarketWatch", "keywords": "美股盘前, 市场快讯", "url": "http://feeds.marketwatch.com/marketwatch/topstories/"},
    ],
    "科技/学术": [
        {"site": "Nature (自然)", "keywords": "硬核科学, 前沿发现", "url": "https://www.nature.com/nature.rss"},
        {"site": "Science (科学)", "keywords": "基础研究, 学术动态", "url": "https://www.science.org/rss/news_current.xml"},
        {"site": "MIT Technology Review", "keywords": "AI大模型, 芯片半导体", "url": "https://www.technologyreview.com/feed/"},
        {"site": "Wired (连线杂志)", "keywords": "极客文化, 科技社会学", "url": "https://www.wired.com/feed/rss"},
    ],
    "杂志/评论/博客": [
        {"site": "The Economist (经济学人)", "keywords": "全球宏观, 经济周期", "url": "https://www.economist.com/finance-and-economics/rss.xml"},
        {"site": "Foreign Affairs (外交事务)", "keywords": "大国博弈, 外交政策", "url": "https://www.foreignaffairs.com/rss.xml"},
        {"site": "Politico (政客)", "keywords": "党政关系, 政策变动", "url": "https://rss.politico.com/politics-news.xml"},
        {"site": "Axios (阿克西奥斯)", "keywords": "政经简报, 内部爆料", "url": "https://api.axios.com/feed/"},
        {"site": "The Atlantic (大西洋月刊)", "keywords": "深度评论, 文化政治", "url": "https://www.theatlantic.com/feed/all/"},
    ],
    "英国/欧洲媒体": [
        {"site": "Financial Times (金融时报)", "keywords": "欧洲央行, 跨国金融", "url": "https://www.ft.com/news-feed?format=rss"},
        {"site": "The Guardian (卫报)", "keywords": "左翼视角, 气候与人权", "url": "https://www.theguardian.com/world/rss"},
        {"site": "Der Spiegel (明镜周刊-德语区)", "keywords": "欧盟政策, 德国工业", "url": "https://www.spiegel.de/international/index.rss"},
        {"site": "Le Monde (世界报-法语区)", "keywords": "法国政局, 欧洲防务", "url": "https://www.lemonde.fr/en/rss/une.xml"},
    ],
    "亚洲/大洋洲媒体": [
        {"site": "South China Morning Post (南华早报)", "keywords": "港股, 中国宏观, 亚洲地缘", "url": "https://www.scmp.com/rss/318208/feed"},
        {"site": "Nikkei (日经新闻)", "keywords": "日本央行, 半导体供应链", "url": "https://asia.nikkei.com/rss/feed/nvapi/details"},
        {"site": "The Sydney Morning Herald", "keywords": "澳洲矿业, 亚太贸易", "url": "https://www.smh.com.au/rss/world.xml"},
        {"site": "Times of India (印度时报)", "keywords": "新兴市场, 印度经济", "url": "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms"},
    ]
}

def translate_with_deepseek(text):
    if not text:
        return "无标题"

    safe_text = text.replace('|', '-').replace('\n', ' ')
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的国际政经与金融翻译员。请将英文新闻标题翻译成地道的简体中文。直接输出翻译结果，不要多余解释。"},
            {"role": "user", "content": safe_text}
        ],
        "temperature": 0.1
    }

    try:
        response = requests.post(
            "https://api.deepseek.com/chat/completions",
            headers=headers,
            json=payload,
            timeout=20 # DeepSeek 直连不走代理
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"  -> DeepSeek 翻译异常: {str(e)[:50]}...")
        return safe_text

def fetch_and_format_news():
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    md_content = f"# 🌍 全球核心媒体政经与市场简报 ({today_str})\n\n"
    md_content += "*(本报告由 Python 自动抓取并经由 DeepSeek AI 翻译生成)*\n\n"
    md_content += "| 分类 | 网站 (中英文) | 详细关键词与分类 | 最新中文标题与原文链接 |\n"
    md_content += "| :--- | :--- | :--- | :--- |\n"

    total_sites = sum(len(sites) for sites in RSS_SOURCES.values())
    current_site = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml"
    }

    for category, sites in RSS_SOURCES.items():
        for site_info in sites:
            current_site += 1
            site_name = site_info["site"]
            keywords = site_info["keywords"]
            url = site_info["url"]

            print(f"[{current_site}/{total_sites}] 正在抓取: {site_name} ...")

            try:
                response = http_session.get(url, headers=headers, timeout=20)

                if response.status_code == 403:
                    md_content += f"| **{category}** | {site_name} | *{keywords}* | IP 被网站防火墙拦截 (403) |\n"
                    continue

                response.raise_for_status()
                feed = feedparser.parse(response.content)
                top_entries = feed.entries[:3]

                if not top_entries:
                    md_content += f"| **{category}** | {site_name} | *{keywords}* | 网站无更新 |\n"
                else:
                    news_links_html = ""
                    for entry in top_entries:
                        original_title = entry.get('title', '无标题')
                        link = entry.get('link', '#')
                        zh_title = translate_with_deepseek(original_title)

                        # ==========================================
                        # 排版优化：直接使用 Markdown 链接语法，并加上换行符
                        # 这样渲染出来就是蓝色的标题，且每条新闻占据独立的一行
                        # ==========================================
                        news_links_html += f"• [{zh_title}]({link})<br><br>"

                    md_content += f"| **{category}** | {site_name} | *{keywords}* | {news_links_html} |\n"

                time.sleep(1)

            except requests.exceptions.RequestException as e:
                md_content += f"| **{category}** | {site_name} | *{keywords}* | 代理节点连接超时 |\n"
            except Exception as e:
                md_content += f"| **{category}** | {site_name} | *{keywords}* | 解析异常 |\n"

    return md_content, today_str

def send_email_with_md(md_content, date_str):
    import socks
    import socket

    msg = MIMEMultipart('alternative') # 使用 alternative 以支持富文本 HTML
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"📊 核心政经与大宗商品简报 - {date_str}"

    # ==========================================
    # HTML 渲染优化：将 Markdown 转为带 CSS 样式的精美表格
    # ==========================================
    html_body = markdown.markdown(md_content, extensions=['tables'])
    html_template = f"""
    <html>
    <head>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; }}
      table {{ border-collapse: collapse; width: 100%; max-width: 1200px; margin-top: 20px; }}
      th, td {{ border: 1px solid #e0e0e0; text-align: left; padding: 12px; vertical-align: top; }}
      th {{ background-color: #f8f9fa; font-weight: bold; color: #444; }}
      a {{ color: #1a73e8; text-decoration: none; font-weight: 500; }}
      a:hover {{ text-decoration: underline; }}
      td:nth-child(4) {{ min-width: 300px; }} /* 保证新闻标题列有足够宽度 */
    </style>
    </head>
    <body>
      {html_body}
    </body>
    </html>
    """

    # 同时发送纯文本和富文本 HTML，邮箱客户端会自动优先展示 HTML
    part1 = MIMEText(md_content, 'plain', 'utf-8')
    part2 = MIMEText(html_template, 'html', 'utf-8')
    msg.attach(part1)
    msg.attach(part2)

    # 依然保留 Markdown 作为附件，方便你本地存档
    filename = f"Global_Intelligence_{date_str}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(md_content)

    with open(filename, "rb") as f:
        attach = MIMEApplication(f.read(), _subtype="markdown")
        attach.add_header('Content-Disposition', 'attachment', filename=filename)
        msg.attach(attach)

    # 安全地局部接管 socket
    default_socket = socket.socket
    socks.set_default_proxy(socks.SOCKS5, "127.0.0.1", 7897)
    socket.socket = socks.socksocket

    try:
        print("\n正在连接 Gmail SMTP 服务器发送邮件...")
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ 精美的 HTML 简报已成功发送至你的 Gmail 邮箱！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
    finally:
        socket.socket = default_socket
        if os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    print("=== 开始构建全球媒体情报网 ===")
    markdown_data, current_date = fetch_and_format_news()
    send_email_with_md(markdown_data, current_date)
