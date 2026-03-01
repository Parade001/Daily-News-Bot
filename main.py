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
import markdown

# ================== 核心配置区 (从 GitHub Secrets 读取) ==================
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

# 工业级网络 Session 初始化
http_session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
http_session.mount('http://', adapter)
http_session.mount('https://', adapter)

http_session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Referer": "https://www.google.com/",  # 模拟从搜索引擎跳转，能绕过很多拦截
    "Cache-Control": "max-age=0"
})
# ================== 天气与生活指数模块 ==================
CITIES = {
    "法国巴黎": {"lat": 48.8566, "lon": 2.3522, "tz": "Europe/Paris"},
    "湖北武汉": {"lat": 30.5928, "lon": 114.3055, "tz": "Asia/Shanghai"},
    "湖北汉川": {"lat": 30.6550, "lon": 113.8385, "tz": "Asia/Shanghai"},
    "广东惠州": {"lat": 23.1115, "lon": 114.4162, "tz": "Asia/Shanghai"}
}

def get_weather_description(code):
    weather_map = {
        0: "☀️ 晴朗", 1: "🌤️ 大部晴朗", 2: "⛅ 多云", 3: "☁️ 阴天",
        45: "🌫️ 雾", 48: "🌫️ 结霜浓雾", 51: "🌦️ 轻微毛毛雨", 53: "🌧️ 毛毛雨",
        55: "🌧️ 密集毛毛雨", 61: "🌧️ 小雨", 63: "🌧️ 中雨", 65: "🌧️ 大雨",
        71: "🌨️ 小雪", 73: "🌨️ 中雪", 75: "🌨️ 大雪", 95: "⛈️ 雷暴"
    }
    return weather_map.get(code, "☁️ 未知")

def fetch_weather_data():
    weather_md = "## 🌤️ 重点城市今日天气与生活指数\n\n"
    weather_md += "| 城市 | 今日核心气象 | 户外指数 | 生活建议 (六项指标) | 未来三天趋势 |\n"
    weather_md += "| :--- | :--- | :--- | :--- | :--- |\n"

    for city, coords in CITIES.items():
        try:
            w_res = http_session.get(f"https://api.open-meteo.com/v1/forecast?latitude={coords['lat']}&longitude={coords['lon']}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,visibility&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&timezone={coords['tz']}", timeout=15).json()
            aqi_res = http_session.get(f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={coords['lat']}&longitude={coords['lon']}&current=european_aqi&timezone={coords['tz']}", timeout=15).json()

            cur = w_res['current']
            daily = w_res['daily']
            aqi_val = aqi_res.get('current', {}).get('european_aqi', 'N/A')

            # 指标计算
            atemp = cur['apparent_temperature']
            dress = "👕 清凉短袖" if atemp >= 28 else ("🧥 适宜薄外套" if atemp >= 18 else "🧣 注意保暖")
            uv = daily['uv_index_max'][0]
            sun = "🧴 无需防晒" if uv < 3 else "☀️ 建议防晒"
            code = cur['weather_code']
            sport = "🏃 宜户外运动" if (isinstance(aqi_val, int) and aqi_val <= 100 and code <= 2) else "🏠 建议室内"
            will_rain = any(c >= 51 for c in daily['weather_code'][:4])
            car = "🚗 宜洗车" if not will_rain else "🚿 不宜洗车"
            umbrella = "☂️ 有雨带伞" if code >= 51 else "👓 无需带伞"
            temp_diff = daily['temperature_2m_max'][0] - daily['temperature_2m_min'][0]
            cold = "🤒 较易感冒" if (temp_diff > 10 or atemp < 8) else "✅ 风险较低"

            core = f"**{get_weather_description(code)}**<br>🌡️ {cur['temperature_2m']}°C<br>🌬️ {cur['wind_speed_10m']}km/h"
            outdoor = f"😷 AQI: {aqi_val}<br>☀️ UV: {uv}<br>👁️ {cur['visibility']/1000:.1f}km"
            advice = f"{dress}<br>{sun}<br>{sport}<br>{car}<br>{umbrella}<br>{cold}"

            future = ""
            for i in range(1, 4):
                future += f"• {daily['time'][i][-5:]}: {get_weather_description(daily['weather_code'][i]).split(' ')[0]} {daily['temperature_2m_min'][i]}~{daily['temperature_2m_max'][i]}°C<br>"

            weather_md += f"| **{city}** | {core} | {outdoor} | {advice} | {future} |\n"
            time.sleep(1)
        except:
            weather_md += f"| **{city}** | 接口超时 | - | - | - |\n"
    return weather_md + "\n---\n"

def fetch_rss_content(url):
    """
    专门解决机器之心、The Verge 等源解析失败的增强型函数
    """
    try:
        # 核心：必须用 http_session 发起请求，带上 headers
        response = http_session.get(url, timeout=20)
        response.encoding = 'utf-8' # 强制编码，防止 text.txt 里的乱码

        # 将请求到的文本交给 feedparser 解析
        feed = feedparser.parse(response.text)

        # 兼容性检查：如果 feedparser 没解析出标题，尝试从 channel 里找
        if not feed.entries:
            # 有些源格式特殊，需要重新解析
            feed = feedparser.parse(response.content)

        return feed.entries
    except Exception as e:
        print(f"抓取失败 {url}: {e}")
        return []
# ================== 完整 28 个 RSS 源 ==================
RSS_SOURCES = {
    "国际/美国主流媒体": [
        {"site": "The New York Times (纽约时报)", "keywords": "美国政治, 国际关系", "url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml"},
        {"site": "The Washington Post (华盛顿邮报)", "keywords": "华盛顿内幕, 全球视野", "url": "https://feeds.washingtonpost.com/rss/world"},
        {"site": "The Washington Post (华盛顿邮报)", "keywords": "商业新闻 (Business)", "url": "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml"},
        {"site": "The Washington Post (华盛顿邮报)", "keywords": "市场新闻 (Markets)", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
        {"site": "CNN", "keywords": "突发新闻, 地缘冲突", "url": "http://rss.cnn.com/rss/edition_world.rss"},
        {"site": "Fox News (福克斯新闻)", "keywords": "保守派视角, 美国内政", "url": "http://feeds.foxnews.com/foxnews/world"},
        {"site": "Los Angeles Times (洛杉矶时报)", "keywords": "美国西海岸, 亚太焦点", "url": "https://www.latimes.com/world/rss2.0.xml"},
        {"site": "NPR (国家公共广播电台)", "keywords": "美国内政, 国际时事", "url": "https://feeds.npr.org/1004/rss.xml"},
    ],
    "商业/财经": [
        {"site": "Bloomberg (彭博社)", "keywords": "大宗商品, 贵金属, 美联储", "url": "https://feeds.bloomberg.com/markets/news.rss"},
        {"site": "Seeking Alpha (美股投研)", "keywords": "个股异动, 市场情绪", "url": "https://seekingalpha.com/market_currents.xml"},
        {"site": "Forbes (福布斯)", "keywords": "财富管理, 商业领袖", "url": "https://www.forbes.com/business/feed/"},
        {"site": "MarketWatch", "keywords": "美股盘前, 市场快讯", "url": "http://feeds.marketwatch.com/marketwatch/topstories/"},
        {"site": "Yahoo Finance (雅虎财经)", "keywords": "美股大盘, 宏观经济", "url": "https://finance.yahoo.com/news/rss"},
        {"site": "CNBC", "keywords": "投资策略, 商业巨头", "url": "https://www.cnbc.com/id/10000664/device/rss/rss.html"},
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
        {"site": "Nikkei (日经新闻)", "keywords": "日本央行, 半导体供应链", "url": "https://asia.nikkei.com/rss/feed/nar"},
        {"site": "The Sydney Morning Herald", "keywords": "澳洲矿业, 亚太贸易", "url": "https://www.smh.com.au/rss/world.xml"},
        {"site": "Times of India (印度时报)", "keywords": "新兴市场, 印度经济", "url": "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms"},
        {"site": "South China Morning Post (南华早报)", "keywords": "中国外交, 宏观经济", "url": "https://www.scmp.com/rss/91/feed"},
        {"site": "TechCrunch", "keywords": "初创企业, 风投动态", "url": "https://techcrunch.com/feed/"},
        {"site": "The Verge", "keywords": "消费电子, 科技政策", "url": "https://www.theverge.com/rss/index.xml"},
    ],
    "股市实战/宏观": [
        {"site": "Seeking Alpha", "keywords": "美股研报, 个股策略", "url": "https://seekingalpha.com/market_currents.xml"},
        {"site": "Investing.com", "keywords": "宏观数据, 利率前瞻", "url": "https://www.investing.com/rss/news.rss"},
    ],
    "军事/地缘博弈": [
        {"site": "Defense News", "keywords": "全球防务, 军工产业", "url": "https://www.defensenews.com/arc/outboundfeeds/rss/category/global/"},
        {"site": "USNI News", "keywords": "印太局势, 海权博弈", "url": "https://news.usni.org/feed"},
        {"site": "The War Zone", "keywords": "先进武器, 冲突实录", "url": "https://www.twz.com/feed/"},
    ],
    "Web开发/前沿技术": [
        {"site": "Hacker News", "keywords": "技术趋势, 创业逻辑", "url": "https://news.ycombinator.com/rss"},
        {"site": "InfoQ", "keywords": "架构演进, AI编程", "url": "https://www.infoq.com/feed"},
        {"site": "The New Stack", "keywords": "Web3, 云计算, 开发者生态", "url": "https://thenewstack.io/blog/feed/"},
    ],
    "AI/大模型/前沿科技": [
        {"site": "Hugging Face", "keywords": "开源模型, 论文复现", "url": "https://huggingface.co/blog/feed.xml"},
        {"site": "OpenAI Blog", "keywords": "AGI, 风向标", "url": "https://openai.com/news/rss.xml"},
        # VentureBeat 的 AI 频道是目前全球公认最难封杀的 RSS
        {"site": "The Decoder", "keywords": "大模型, 行业前瞻", "url": "https://the-decoder.com/feed/"}, # 专门做AI的，非常稳
        {"site": "Artificial Intelligence News", "keywords": "AI技术, 落地", "url": "https://www.artificialintelligence-news.com/feed/"},
        {"site": "VentureBeat AI", "keywords": "大模型, 商业落地", "url": "https://venturebeat.com/category/ai/feed/"},
        {"site": "Wired Science", "keywords": "前沿科学, 生物技术", "url": "https://www.wired.com/feed/category/science/latest/rss"},
        {"site": "New Scientist", "keywords": "量子计算, 基因编辑", "url": "https://www.newscientist.com/feed/home/"},
        {"site": "Space.com", "keywords": "星际航行, 火星计划", "url": "https://www.space.com/feeds/all"},
        {"site": "IEEE Spectrum", "keywords": "半导体, 机器人工程", "url": "https://spectrum.ieee.org/rss/fulltext"},
    ],
    "科幻/影视/深度评论": [
        # 完美的沙丘/科幻深度源，来自 Tor (世界顶级科幻出版商)
        {"site": "Tor.com (科幻专栏)", "keywords": "硬核科幻, 史诗评论", "url": "https://www.reactormag.com/feed/"},
        # 换用 Polygon 的影视区，比 The Verge 对爬虫更友好
        {"site": "Den of Geek", "keywords": "极客文化, 影视彩蛋", "url": "https://www.denofgeek.com/feed/"},
    ]
}

def translate_with_deepseek(text):
    if not text: return "无标题"
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}

    # 修改指令：增加“严禁换行、禁止摘要、严禁输出列表”的硬性要求
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "你是一个专业的国际政经翻译。请将输入的新闻标题翻译为地道的简体中文。要求：1. 严禁输出任何换行符或回车；2. 严禁进行摘要、扩写或生成列表，仅保留翻译；3. 直接输出翻译结果。"},
            {"role": "user", "content": text}
        ],
        "temperature": 0.1
    }

    try:
        response = requests.post("https://api.deepseek.com/chat/completions", headers=headers, json=payload, timeout=20)
        result = response.json()['choices'][0]['message']['content'].strip()
        # 二次保险：强行替换掉结果中的所有真实换行符
        return result.replace('\n', ' ').replace('\r', ' ').replace('|', '-')
    except:
        return text.replace('|', '-')

def fetch_and_format_content():
    tz = datetime.timezone(datetime.timedelta(hours=8))
    today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")

    md_content = f"# 🌍 全球宏观情报与专属气象简报 ({today_str})\n\n"
    md_content += fetch_weather_data()

    md_content += "## 📰 核心政经与大宗商品速递\n\n"
    md_content += "| 分类 | 网站 (中英文) | 详细关键词与分类 | 最新中文标题与原文链接 |\n"
    md_content += "| :--- | :--- | :--- | :--- |\n"

    total_sites = sum(len(sites) for sites in RSS_SOURCES.values())
    current_site = 0

    for category, sites in RSS_SOURCES.items():
        for site_info in sites:
            current_site += 1
            site_name = site_info["site"]
            keywords = site_info["keywords"]
            url = site_info["url"]

            print(f"[{current_site}/{total_sites}] 抓取资讯: {site_name}")
            try:
                res = http_session.get(url, timeout=15)

                # 1. 核心修复：坚决使用 res.content (原始字节流) 喂给 feedparser
                feed = feedparser.parse(res.content)

                # 2. 如果标准解析失败，尝试暴力正则提取 (专治各种不规范的 RSS)
                if not feed.entries:
                    import re
                    # 尝试提取 <title> 和 <link>
                    html_text = res.text
                    titles = re.findall(r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>', html_text, re.IGNORECASE)
                    links = re.findall(r'<link>(.*?)</link>', html_text, re.IGNORECASE)

                    # 过滤掉属于 <channel> 的全局标题 (通常是前1-2个)
                    # text.txt 显示全局标题为 <title>Synced</title> 和 <link>https://syncedreview.com</link>
                    if len(titles) > 1 and len(links) > 1:
                        titles = titles[1:]
                        links = links[1:]

                    # 手动构造前3条 entry 字典
                    feed.entries = [{"title": t, "link": l} for t, l in zip(titles, links)]

                news_links_html = ""
                # 仅取前 3 条新闻
                for entry in feed.entries[:3]:
                    # 字典取值改为兼容模式
                    original_title = entry.get('title', '无标题') if isinstance(entry, dict) else entry.title
                    link = entry.get('link', '#') if isinstance(entry, dict) else entry.link

                    zh_title = translate_with_deepseek(original_title)
                    news_links_html += f"• [{zh_title}]({link})<br><br>"

                md_content += f"| **{category}** | {site_name} | *{keywords}* | {news_links_html} |\n"
                time.sleep(1)
            except Exception as e:
                print(f"Error parsing {site_name}: {e}")
                md_content += f"| **{category}** | {site_name} | *{keywords}* | [数据解析异常] |\n"
            except:
                md_content += f"| **{category}** | {site_name} | *{keywords}* | [网络抓取暂时失败] |\n"

    return md_content, today_str

def send_email_with_md(md_content, date_str):
    msg = MIMEMultipart('mixed')
    msg['From'], msg['To'], msg['Subject'] = SENDER_EMAIL, RECEIVER_EMAIL, f"📊 全球宏观情报与气象简报 - {date_str}"

    alt_part = MIMEMultipart('alternative')
    html_body = markdown.markdown(md_content, extensions=['tables'])
    html_template = f"""
    <html><head><style>
      body {{ font-family: sans-serif; line-height: 1.6; color: #333; }}
      table {{ border-collapse: collapse; width: 100%; margin-top: 20px; font-size: 13px; }}
      th, td {{ border: 1px solid #e0e0e0; text-align: left; padding: 10px; vertical-align: top; }}
      th {{ background-color: #f8f9fa; font-weight: bold; color: #444; }}
      a {{ color: #1a73e8; text-decoration: none; font-weight: 500; }}
      td:nth-child(4) {{ min-width: 320px; }}
    </style></head>
    <body>{html_body}</body></html>
    """

    alt_part.attach(MIMEText(md_content, 'plain', 'utf-8'))
    alt_part.attach(MIMEText(html_template, 'html', 'utf-8'))
    msg.attach(alt_part)

    filename = f"Report_{date_str}.md"
    with open(filename, "w", encoding="utf-8") as f: f.write(md_content)
    with open(filename, "rb") as f:
        attach = MIMEApplication(f.read(), _subtype="markdown")
        attach.add_header('Content-Disposition', 'attachment', filename=filename)
        msg.attach(attach)

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ 简报发送成功！")
    except Exception as e: print(f"❌ 失败: {e}")
    finally:
        if os.path.exists(filename): os.remove(filename)

if __name__ == "__main__":
    data, date = fetch_and_format_content()
    send_email_with_md(data, date)
