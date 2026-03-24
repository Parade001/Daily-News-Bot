import os
import json
import datetime
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
import markdown

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
    """
    负责将 Markdown 转换为 HTML，并同时作为正文和附件发送
    """
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

    # 2. 组装正文 (支持纯文本和 HTML 双击退)
    alt_part = MIMEMultipart('alternative')
    alt_part.attach(MIMEText(md_content, 'plain', 'utf-8'))
    alt_part.attach(MIMEText(html_template, 'html', 'utf-8'))
    msg.attach(alt_part)

    # 3. 核心修复：生成并挂载 Markdown 附件
    filename = f"Report_{date_str}.md"
    try:
        # 将内容写入本地临时文件
        with open(filename, "w", encoding="utf-8") as f: 
            f.write(md_content)
        # 读取本地文件并挂载为附件
        with open(filename, "rb") as f:
            attach = MIMEApplication(f.read(), _subtype="markdown")
            attach.add_header('Content-Disposition', 'attachment', filename=filename)
            msg.attach(attach)
    except Exception as e:
        print(f"⚠️ 附件生成或挂载失败，但不影响正文发送: {e}")

    # 4. 发送邮件网络请求
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=30)
        server.starttls()
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print("✅ 简报与附件发送成功！")
    except Exception as e: 
        print(f"❌ 邮件发送彻底失败: {e}")
    finally:
        # 工程化：无论成功失败，必须清理 Actions 服务器上的临时文件，防止污染
        if os.path.exists(filename): 
            os.remove(filename)

if __name__ == "__main__":
    # 1. 记录系统启动时间
    start_time = time.time()
    
    # 2. 初始化环境与时间戳
    config = load_config()
    # 强制使用东八区（北京时间）生成日期字符串
    today = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")
    
    # 3. 核心调度：按顺序抓取三大模块
    print("⏳ 正在抓取天气数据...")
    weather_data = fetch_weather_data(config['cities'])
    
    print("⏳ 正在运行宏观量化引擎...")
    # 注意：此处必须传入 FRED_API_KEY
    macro_data = fetch_macro_indicators(FRED_API_KEY) 
    
    print("⏳ 正在抓取并翻译全球 RSS 新闻...")
    rss_data = fetch_rss_news(config['rss_sources'], DEEPSEEK_API_KEY)
    
    # 4. 计算耗时
    end_time = time.time()
    elapsed_seconds = end_time - start_time
    
    # 5. 组装最终 Markdown 文本
    # 使用内联 HTML 控制耗时文字的样式，避免被 Markdown 默认的 # 标签放大加粗
    final_report = f"# 🌍 全球宏观情报与专属气象简报 ({today}) <span style='font-size: 14px; font-weight: normal; font-style: italic; color: #666;'> (本次执行用时: {elapsed_seconds:.1f} 秒)</span>\n\n"
    
    final_report += weather_data
    final_report += macro_data
    final_report += rss_data
    
    # 6. 触发邮件发送
    print("⏳ 正在打包并发送邮件...")
    send_email(final_report, today)
