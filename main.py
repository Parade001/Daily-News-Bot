import os
import json
import datetime
import time  # 引入时间模块
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import markdown

from weather import fetch_weather_data
from macro import fetch_macro_indicators
from rss_parser import fetch_rss_news

# 从环境变量读取
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")

def load_config():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json'), 'r', encoding='utf-8') as f:
        return json.load(f)

def send_email(md_content, date_str):
    msg = MIMEMultipart('mixed')
    msg['From'], msg['To'], msg['Subject'] = SENDER_EMAIL, RECEIVER_EMAIL, f"📊 全球宏观情报与气象简报 - {date_str}"

    html_body = markdown.markdown(md_content, extensions=['tables'])
    html_template = f"""<html><head><style>
      body {{ font-family: sans-serif; line-height: 1.6; color: #333; }}
      table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
      th, td {{ border: 1px solid #e0e0e0; padding: 10px; vertical-align: top; }}
      th {{ background-color: #f8f9fa; font-weight: bold; color: #444; }}
      a {{ color: #1a73e8; text-decoration: none; font-weight: 500; }}
      td:nth-child(4) {{ min-width: 320px; }}
    </style></head><body>{html_body}</body></html>"""

    alt_part = MIMEMultipart('alternative')
    alt_part.attach(MIMEText(md_content, 'plain', 'utf-8'))
    alt_part.attach(MIMEText(html_template, 'html', 'utf-8'))
    msg.attach(alt_part)

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ 简报发送成功！")
    except Exception as e:
        print(f"❌ 失败: {e}")

if __name__ == "__main__":
    # 1. 记录脚本启动时间
    start_time = time.time()

    config = load_config()
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")

    # 分别获取各模块数据
    weather_data = fetch_weather_data(config['cities'])
    macro_data = fetch_macro_indicators()
    rss_data = fetch_rss_news(config['rss_sources'], DEEPSEEK_API_KEY)

    # 2. 记录数据抓取结束时间，并计算耗时
    end_time = time.time()
    elapsed_seconds = end_time - start_time

    # 3. 构造标题，使用 HTML span 标签控制右侧副标题的样式（取消加粗、斜体、缩小字号、灰色）
    report = f"# 🌍 全球宏观情报与专属气象简报 ({today}) <span style='font-size: 14px; font-weight: normal; font-style: italic; color: #666;'> (本次执行用时: {elapsed_seconds:.1f} 秒)</span>\n\n"

    # 拼接正文内容
    report += weather_data
    report += macro_data
    report += rss_data

    # 4. 发送邮件
    send_email(report, today)
