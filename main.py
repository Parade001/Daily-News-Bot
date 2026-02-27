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
        {"site": "The Guardian (卫卫报)", "keywords": "左翼视角, 气候与人权", "url": "https://www.theguardian.com/world/rss"},
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
                feed = feedparser.parse(res.content)
                news_links_html = ""
                # 仅取前 3 条新闻，确保表格高度可控
                for entry in feed.entries[:3]:
                    original_title = entry.get('title', '无标题')
                    link = entry.get('link', '#')
                    # 获取翻译，内部已处理掉换行符
                    zh_title = translate_with_deepseek(original_title)

                    # 按照图1样式：圆点 + 蓝色链接，使用 <br> 进行单元格内换行（不会破坏表格行）
                    news_links_html += f"• [{zh_title}]({link})<br><br>"

                # 拼接成 Markdown 表格行，这一行必须是完整的
                md_content += f"| **{category}** | {site_name} | *{keywords}* | {news_links_html} |\n"
                time.sleep(1)
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
