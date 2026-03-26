# 🌍 Global Macro Intelligence & Weather Briefing System
# (全球宏观情报与气象简报系统)

[English Version](#english-version) | [中文版本](#chinese-version)

---

<h2 id="chinese-version">🇨🇳 中文版本</h2>

### 📖 项目简介 (Overview)
本项目是一个全自动、机构级的“宏观量化交易与生活简报系统”。它旨在通过高并发的网络架构，每天清晨极速抓取全球宏观经济指标、底层流动性数据、国际政经新闻以及重点城市气象信息。系统内置动态量化打分引擎（Z-Score & 动量）与大语言模型（LLM）翻译，最终将复杂的金融数据转化为直观的、带有操作建议的 Markdown / HTML 邮件研报发送给用户。

### 🚀 核心特性 (Key Features)
- **极限并发性能**：全链路采用 `concurrent.futures` 线程池调度，底层 TCP 连接池扩容至 100，将原本需 400 秒以上的 I/O 阻塞时间压缩至 10~15 秒。
- **动态量化引擎**：内置 Robust Z-Score 与 3 日动量一阶导算法，对实际利率、流动性水位、信用利差等进行动态解读，并输出美股 (VOO)、黄金 (18.HK)、大宗商品 (COPX) 的仓位风控建议。
- **大模型批量翻译**：接入 DeepSeek API，采用带序号的 Batch 处理策略合并翻译请求，大幅降低 Token 消耗与网络握手延迟。
- **高可用网络护城河**：具备多跳板穿透、Google Translate 降维代理（针对机构级 WAF）、多期限降级（针对 HIBOR 等场外断流数据）以及 429 智能指数退避重试机制。

### 📂 核心文件架构说明 (Project Structure & Modules)

#### 1. `main.py` (主调度与渲染引擎)
**功能**：系统的入口点与顶层控制器。
- **顶层并发**：开启独立线程同时唤醒 `weather`, `macro`, `rss_parser` 三大核心模块，实现“木桶效应”极限提速。
- **模块级容错**：捕获各子系统的顶层异常。即使个别接口或大模型 API 宕机，也能保证正常模块的数据被成功汇总，避免全局崩溃。
- **邮件渲染与挂载**：将 Markdown 数据转换为带有精美 CSS 样式的 HTML 邮件正文，同时物理生成 `.md` 源文件作为附件发送，随后自动清理。

#### 2. `macro.py` (宏观量化与动态研判引擎)
**功能**：系统的金融大脑。
- **20+ 异步指标抓取**：并发抓取 FRED (美联储), Yahoo Finance, Westmetall (LME铜), 中银香港 (BOCHK 离岸人民币流动性) 等数据源。
- **金融模型计算**：计算包括 MA200 均线、移动斜率、波动率 Z 值、以及核心因子的 Robust Z-Score 和动量极值。
- **风控与熔断层**：基于复合风险指数与跨资产相关性，动态输出减仓、限仓或“保留底仓防深V”的熔断指令。
- **动态解读引擎 (Dynamic Analysis)**：抛弃枯燥的绝对数值，基于当日数据直接输出如“🚨 离岸抽水”、“🌊 放水周期”、“🔥 物理逼空”等交易员视角的白话解读。

#### 3. `rss_parser.py` (政经新闻并发与智能翻译模块)
**功能**：全球新闻监听与翻译。
- **满载并发抓取**：根据配置源数量动态分配线程池（最高 50 线程），瞬间拉取全部 RSS 节点数据。
- **大模型聚合翻译**：将传统“逐条翻译”重构为“打包编号翻译”，单网站仅调用 1 次 DeepSeek API。随后利用精准正则表达式将翻译结果还原拆分，兼顾了成本与速度。

#### 4. `weather.py` (智能气象与生活指数模块)
**功能**：定制化的户外起居指导。
- 并发请求 Open-Meteo 的天气与空气质量 (AQI) 接口。
- **六维生活指数**：结合体感温度、UV、降水概率与能见度，智能推算“穿衣”、“防晒”、“Zone 2 户外运动”、“洗车”、“带伞”、“感冒风险”等高频生活建议。
- 具备接口级降级策略（如 AQI 宕机不影响天气主面板显示）。

#### 5. `http_client.py` (全局高可用网络底层)
**功能**：穿甲弹级的 HTTP 请求伪装与连接池管理。
- **连接池暴扩**：将 `requests.Session` 的默认连接池大小提升至 100，为百并发线程提供充足的 TCP 通道。
- **429 智能熔断**：配置 `urllib3.util.retry`，针对高频请求易触发的 429 (Too Many Requests) 及 5xx 错误，执行带回退因子的自动重试。
- 全局注入统一的 `User-Agent` 与泛用性 `Accept` 头部，降低被 Cloudflare 等 WAF 拦截的概率。

---

<h2 id="english-version">🇺🇸 English Version</h2>

### 📖 Overview
This project is an automated, institutional-grade "Macro Quantitative Trading and Lifestyle Briefing System". Leveraging a highly concurrent network architecture, it rapidly fetches global macroeconomic indicators, underlying liquidity data, geopolitical news, and customized weather forecasts every morning. Built with a dynamic quantitative scoring engine (Z-Score & Momentum) and Large Language Model (LLM) translation, the system converts complex financial data into intuitive Markdown/HTML email reports with actionable trading advice.

### 🚀 Key Features
- **Extreme Concurrency**: Utilizes `concurrent.futures` thread pools across the entire pipeline with a TCP connection pool expanded to 100, compressing over 400 seconds of I/O blocking time down to 10~15 seconds.
- **Dynamic Quantitative Engine**: Integrates Robust Z-Score and 3-day momentum derivatives to dynamically interpret real rates, liquidity levels, and credit spreads, outputting position risk control advice for S&P 500 (VOO), Gold (18.HK), and Commodities (COPX).
- **LLM Batch Translation**: Integrates the DeepSeek API using an indexed batch processing strategy to merge translation requests, significantly reducing Token usage and network handshake latency.
- **High-Availability Network Moat**: Features multi-hop proxy penetration, Google Translate proxying (to bypass institutional WAFs), multi-tenor fallback (for OTC data like HIBOR), and intelligent exponential backoff for 429 errors.

### 📂 Project Structure & Modules Details

#### 1. `main.py` (Orchestration & Rendering Engine)
**Function**: The entry point and top-level controller of the system.
- **Top-Level Concurrency**: Spawns independent threads to trigger `weather`, `macro`, and `rss_parser` simultaneously, achieving maximum speed by aligning with the slowest module.
- **Module-Level Fault Tolerance**: Catches top-level exceptions for each subsystem. If an API or the LLM goes down, surviving modules are still aggregated and sent, preventing global crashes.
- **Email Assembly**: Converts Markdown into beautifully CSS-styled HTML email bodies, generates a physical `.md` source file as an attachment, and automatically cleans up local storage post-delivery.

#### 2. `macro.py` (Macro Quantitative & Dynamic Analysis Engine)
**Function**: The financial brain of the system.
- **20+ Async Data Fetches**: Concurrently scrapes FRED, Yahoo Finance, Westmetall (LME Copper), and BOCHK (Offshore RMB Liquidity).
- **Financial Modeling**: Computes MA200, slope, Volatility Z-Scores, Robust Z-Scores of core factors, and momentum extremes.
- **Risk Control & Circuit Breakers**: Dynamically outputs commands to reduce, limit, or "maintain base position against V-shape rebounds" based on composite risk indices and cross-asset correlations.
- **Dynamic Analysis Engine**: Replaces static numbers with trader-perspective interpretations (e.g., "🚨 Offshore Liquidity Squeeze", "🌊 Easing Cycle", "🔥 Physical Short Squeeze") based on daily live data.

#### 3. `rss_parser.py` (Concurrent News & Smart Translation Module)
**Function**: Global news monitoring and localization.
- **Max-Load Scraping**: Dynamically allocates thread pools (up to 50 threads) based on configured sources to pull all RSS feeds instantly.
- **Aggregated LLM Translation**: Refactored from "line-by-line" to "numbered batch" translation, calling the DeepSeek API only once per website. It uses precise regex to split and reconstruct the translated results, optimizing both cost and execution speed.

#### 4. `weather.py` (Smart Weather & Lifestyle Index Module)
**Function**: Customized outdoor living guidance.
- Concurrently requests Open-Meteo APIs for weather and Air Quality Index (AQI).
- **Six-Dimensional Lifestyle Index**: Combines apparent temperature, UV index, precipitation probability, and visibility to intelligently deduce high-frequency advice for clothing, sun protection, Zone 2 outdoor running, car washing, umbrella usage, and flu risk.
- Implements endpoint-level degradation (e.g., AQI downtime won't break the main weather dashboard).

#### 5. `http_client.py` (Global High-Availability Network Core)
**Function**: Armor-piercing HTTP request spoofing and connection pooling.
- **Pool Expansion**: Increases the default `requests.Session` connection pool size to 100, providing ample TCP channels for hundreds of concurrent threads.
- **429 Smart Breaker**: Configures `urllib3.util.retry` to execute exponential backoff retries specifically for high-frequency 429 (Too Many Requests) and 5xx errors.
- Injects a unified `User-Agent` and versatile `Accept` headers globally to minimize interception rates by WAFs like Cloudflare.

---
### 🛠 Environment Variables
Please ensure the following environment variables are set before running the system (e.g., via GitHub Actions Secrets):
- `SENDER_EMAIL`: SMTP sender email address.
- `APP_PASSWORD`: App password for the sender email (e.g., Gmail App Password).
- `RECEIVER_EMAIL`: Destination email address for the briefing.
- `DEEPSEEK_API_KEY`: API key for DeepSeek LLM translation.
- `FRED_API_KEY`: API key for St. Louis Fed economic data.

### ⚙️ Usage
Simply execute the main entry script:
```bash
python main.py
