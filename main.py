import os
import json
import datetime
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import markdown
import concurrent.futures  # 【新增】引入并发库

# ================== 引入自建业务模块 ==================
from weather import fetch_weather_data
from macro import fetch_macro_indicators
from rss_parser import fetch_rss_news

# ================== 核心配置区 (从环境变量读取) ==================
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
APP_PASSWORD = os.environ.get("APP_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
FRED_API_KEY = os.environ.get("FRED_API_KEY")

def load_config():
    """读取本地 JSON 配置文件"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def send_email(md_content, date_str):
    """负责将 Markdown 转换为 HTML，并同时作为正文和附件发送"""
    msg = MIMEMultipart('mixed')
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"📊 全球宏观情报与气象简报 - {date_str}"

    # 1. 转换 HTML 并设置极简样式
    html_body = markdown.markdown(md_content, extensions=['tables'])
    html_template = f"""<html><head><style>
      body {{ font-family: sans-serif; line-height: 1.6; color: #333; }}
      table {{ border-collapse: collapse; width: 100%; font-size: 13px; margin-bottom: 20px; }}
      th, td {{ border: 1px solid #e0e0e0; padding: 10px; vertical-align: top; }}
      th {{ background-color: #f8f9fa; font-weight: bold; color: #444; }}
      a {{ color: #1a73e8; text-decoration: none; font-weight: 500; }}
      td:nth-child(4) {{ min-width: 320px; }}
      blockquote {{ border-left: 4px solid #ccc; margin: 0; padding-left: 10px; color: #666; }}
    </style></head><body>{html_body}</body></html>"""

    # 2. 组装正文
    alt_part = MIMEMultipart('alternative')
    alt_part.attach(MIMEText(md_content, 'plain', 'utf-8'))
    alt_part.attach(MIMEText(html_template, 'html', 'utf-8'))
    msg.attach(alt_part)

    # 3. 核心修复：生成并挂载 Markdown 附件
    filename = f"Report_{date_str}.md"
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(md_content)
        with open(filename, "rb") as f:
            attach = MIMEApplication(f.read(), _subtype="markdown")
            attach.add_header('Content-Disposition', 'attachment', filename=filename)
            msg.attach(attach)
    except Exception as e:
        print(f"⚠️ 附件挂载失败: {e}")

    # 4. 发送邮件网络请求
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ 简报与附件发送成功！")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
    finally:
        if os.path.exists(filename): os.remove(filename)

if __name__ == "__main__":
    start_time = time.time()
    config = load_config()
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")

    print("🚀 启动顶层并发调度引擎，同时抓取 天气 / 宏观 / RSS ...")

    # 默认兜底文案（防止某个模块彻底崩溃导致整个排版错乱）
    weather_data = "> ⚠️ 天气模块未能成功加载数据\n\n"
    macro_data = "> ⚠️ 宏观量化模块未能成功加载数据\n\n"
    rss_data = "> ⚠️ 核心政经新闻未能成功加载数据\n\n"

    # 【核心升级】：开启顶层 3 线程并发，将总耗时降至最慢单一模块的耗时
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        future_weather = executor.submit(fetch_weather_data, config['cities'])
        future_macro = executor.submit(fetch_macro_indicators, FRED_API_KEY)
        future_rss = executor.submit(fetch_rss_news, config['rss_sources'], DEEPSEEK_API_KEY)

        # 模块级容错：即使某个子系统因为 API 挂了抛出异常，邮件依然能发出其余模块
        try:
            weather_data = future_weather.result()
        except Exception as e:
            print(f"❌ 天气模块顶层崩溃: {e}")

        try:
            macro_data = future_macro.result()
        except Exception as e:
            print(f"❌ 宏观模块顶层崩溃: {e}")

        try:
            rss_data = future_rss.result()
        except Exception as e:
            print(f"❌ RSS模块顶层崩溃: {e}")

    elapsed_seconds = time.time() - start_time
    print(f"⏱️ 所有数据拉取完毕，总耗时: {elapsed_seconds:.1f} 秒")

    # 组装终极报告
    final_report = f"# 🌍 全球宏观情报与专属气象简报 ({today}) <span style='font-size: 14px; font-weight: normal; font-style: italic; color: #666;'> (本次执行用时: {elapsed_seconds:.1f} 秒)</span>\n\n"
    final_report += weather_data + macro_data + rss_data

    print("⏳ 正在打包并发送邮件...")
    send_email(final_report, today)
