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

# ================== 核心配置区 ==================
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

http_session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[ 500, 502, 503, 504 ])
adapter = HTTPAdapter(max_retries=retries)
http_session.mount('http://', adapter)
http_session.mount('https://', adapter)

# ================== 天气数据获取模块 ==================
CITIES = {
    "法国巴黎": {"lat": 48.8566, "lon": 2.3522, "tz": "Europe/Paris"},
    "湖北武汉": {"lat": 30.5928, "lon": 114.3055, "tz": "Asia/Shanghai"},
    "湖北汉川": {"lat": 30.6550, "lon": 113.8385, "tz": "Asia/Shanghai"},
    "广东惠州": {"lat": 23.1115, "lon": 114.4162, "tz": "Asia/Shanghai"}
}

def get_weather_description(code):
    """将 WMO 气象代码转换为中文描述"""
    weather_map = {
        0: "☀️ 晴朗", 1: "🌤️ 大部晴朗", 2: "⛅ 多云", 3: "☁️ 阴天",
        45: "🌫️ 雾", 48: "🌫️ 结霜浓雾", 51: "🌦️ 轻微毛毛雨", 53: "🌧️ 毛毛雨",
        55: "🌧️ 密集毛毛雨", 61: "🌧️ 小雨", 63: "🌧️ 中雨", 65: "🌧️ 大雨",
        71: "🌨️ 小雪", 73: "🌨️ 中雪", 75: "🌨️ 大雪", 95: "⛈️ 雷暴"
    }
    return weather_map.get(code, "☁️ 未知天气")

def fetch_weather_data():
    """通过 Open-Meteo 获取四个城市的天气及 AQI 数据"""
    weather_md = "## 🌤️ 重点城市今日及未来天气概览\n\n"
    weather_md += "| 城市 | 当天核心气象 (实时/体感) | 户外指数 (AQI/紫外线/能见度) | 未来三天趋势预报 |\n"
    weather_md += "| :--- | :--- | :--- | :--- |\n"

    print("\n=== 开始获取全球气象数据 ===")

    for city, coords in CITIES.items():
        print(f"正在获取 {city} 的天气数据...")
        try:
            # 1. 获取常规气象数据 (包含今日详尽数据和未来趋势)
            weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={coords['lat']}&longitude={coords['lon']}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,visibility&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&timezone={coords['tz']}"
            w_res = http_session.get(weather_url, timeout=10).json()

            # 2. 获取 AQI 数据 (Open-Meteo 的空气质量接口是独立的)
            aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={coords['lat']}&longitude={coords['lon']}&current=european_aqi&timezone={coords['tz']}"
            aqi_res = http_session.get(aqi_url, timeout=10).json()

            # 解析实时数据
            cur = w_res['current']
            daily = w_res['daily']
            aqi_val = aqi_res.get('current', {}).get('european_aqi', 'N/A')

            desc = get_weather_description(cur['weather_code'])
            temp = f"{cur['temperature_2m']}°C"
            feels = f"{cur['apparent_temperature']}°C"
            humidity = f"{cur['relative_humidity_2m']}%"
            # 风速转换为大致的风力等级 (粗略计算: 1m/s ≈ 0.28km/h)
            wind_speed = cur['wind_speed_10m']
            wind_scale = f"{wind_speed} km/h"
            visibility = f"{cur['visibility'] / 1000:.1f} km"
            uv_max = daily['uv_index_max'][0]

            # 评估 AQI 和 紫外线级别
            aqi_status = "🟢 优" if isinstance(aqi_val, int) and aqi_val <= 50 else ("🟡 良" if isinstance(aqi_val, int) and aqi_val <= 100 else "🔴 差")
            uv_status = "高" if uv_max >= 6 else ("中" if uv_max >= 3 else "低")

            # 核心数据排版
            core_data = f"**{desc}**<br>🌡️ 气温：{temp} (体感 {feels})<br>💧 湿度：{humidity}<br>🌬️ 风速：{wind_scale}"
            outdoor_data = f"😷 AQI：{aqi_val} ({aqi_status})<br>☀️ 紫外线：{uv_max} ({uv_status})<br>👁️ 能见度：{visibility}"

            # 未来 3 天趋势排版 (保留简洁性，防止表格过载)
            future_forecast = ""
            for i in range(1, 4):
                f_date = daily['time'][i][-5:] # 取日期如 02-27
                f_desc = get_weather_description(daily['weather_code'][i]).split(" ")[0] # 只取图标
                f_max = daily['temperature_2m_max'][i]
                f_min = daily['temperature_2m_min'][i]
                future_forecast += f"• {f_date}: {f_desc} {f_min}°C ~ {f_max}°C<br>"

            weather_md += f"| **{city}** | {core_data} | {outdoor_data} | {future_forecast} |\n"
            time.sleep(0.5)

        except Exception as e:
            print(f"❌ {city} 气象数据获取失败: {e}")
            weather_md += f"| **{city}** | 气象服务连接异常 | 暂无数据 | 暂无数据 |\n"

    weather_md += "---\n\n"
    return weather_md


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
            timeout=20
        )
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"  -> DeepSeek 翻译异常: {str(e)[:50]}...")
        return safe_text

def fetch_and_format_content():
    tz = datetime.timezone(datetime.timedelta(hours=8))
    today_str = datetime.datetime.now(tz).strftime("%Y-%m-%d")

    # 1. 组合标题与免责声明
    md_content = f"# 🌍 全球宏观情报与专属气象简报 ({today_str})\n\n"
    md_content += "*(本报告由 GitHub Actions 自动构建，融合 Open-Meteo 实时气象及 DeepSeek 翻译引擎)*\n\n"

    # 2. 注入天气模块
    md_content += fetch_weather_data()

    # 3. 构建新闻模块
    md_content += "## 📰 核心政经与大宗商品速递\n\n"
    md_content += "| 分类 | 网站 (中英文) | 详细关键词与分类 | 最新中文标题与原文链接 |\n"
    md_content += "| :--- | :--- | :--- | :--- |\n"

    total_sites = sum(len(sites) for sites in RSS_SOURCES.values())
    current_site = 0

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml"
    }

    print("\n=== 开始获取全球媒体资讯 ===")
    for category, sites in RSS_SOURCES.items():
        for site_info in sites:
            current_site += 1
            site_name = site_info["site"]
            keywords = site_info["keywords"]
            url = site_info["url"]

            print(f"[{current_site}/{total_sites}] 正在抓取资讯: {site_name} ...")

            try:
                response = http_session.get(url, headers=headers, timeout=20)

                if response.status_code == 403:
                    md_content += f"| **{category}** | {site_name} | *{keywords}* | 被网站防火墙拦截 (403) |\n"
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
                        news_links_html += f"• [{zh_title}]({link})<br><br>"

                    md_content += f"| **{category}** | {site_name} | *{keywords}* | {news_links_html} |\n"

                time.sleep(1)

            except requests.exceptions.RequestException as e:
                md_content += f"| **{category}** | {site_name} | *{keywords}* | 节点连接超时 |\n"
            except Exception as e:
                md_content += f"| **{category}** | {site_name} | *{keywords}* | 解析异常 |\n"

    return md_content, today_str

def send_email_with_md(md_content, date_str):
    msg = MIMEMultipart('mixed')
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"📊 全球宏观情报与专属气象简报 - {date_str}"

    alt_part = MIMEMultipart('alternative')

    html_body = markdown.markdown(md_content, extensions=['tables'])
    html_template = f"""
    <html>
    <head>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; }}
      h2 {{ color: #2c3e50; border-bottom: 2px solid #eee; padding-bottom: 5px; margin-top: 30px; }}
      table {{ border-collapse: collapse; width: 100%; max-width: 1200px; margin-top: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
      th, td {{ border: 1px solid #e0e0e0; text-align: left; padding: 12px; vertical-align: top; }}
      th {{ background-color: #f8f9fa; font-weight: bold; color: #444; }}
      a {{ color: #1a73e8; text-decoration: none; font-weight: 500; }}
      a:hover {{ text-decoration: underline; }}
      td:nth-child(4) {{ min-width: 300px; }}
      .weather-table th {{ background-color: #e3f2fd; color: #0277bd; }}
    </style>
    </head>
    <body>
      {html_body}
    </body>
    </html>
    """

    part1 = MIMEText(md_content, 'plain', 'utf-8')
    part2 = MIMEText(html_template, 'html', 'utf-8')
    alt_part.attach(part1)
    alt_part.attach(part2)

    msg.attach(alt_part)

    filename = f"Global_Intelligence_{date_str}.md"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(md_content)

    with open(filename, "rb") as f:
        attach = MIMEApplication(f.read(), _subtype="markdown")
        attach.add_header('Content-Disposition', 'attachment', filename=filename)
        msg.attach(attach)

    try:
        print("\n正在连接 Gmail SMTP 服务器发送邮件...")
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ HTML 简报正文及 Markdown 附件已成功发送至你的邮箱！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

if __name__ == "__main__":
    print("=== 开始构建智能化日常简报 (GitHub Actions 环境) ===")
    if not all([SENDER_EMAIL, APP_PASSWORD, DEEPSEEK_API_KEY]):
        print("❌ 环境变量未正确配置！请检查 GitHub Secrets。")
        exit(1)

    final_md_data, current_date = fetch_and_format_content()
    send_email_with_md(final_md_data, current_date)
