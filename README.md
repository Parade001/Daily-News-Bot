# 🌍 Global Macro Intelligence & Weather Briefing System
# (全球宏观情报与气象简报系统)

![Python](https://img.shields.io/badge/Python-3.9+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Build](https://img.shields.io/badge/Build-GitHub_Actions-orange.svg)

[English Version](#english-version) | [中文版本](#chinese-version)

---

<h2 id="chinese-version">🇨🇳 中文版本</h2>

### 📖 项目简介 (Overview)
本项目是一个全自动、机构级的“宏观量化交易与生活简报系统”。它旨在通过高并发的网络架构，每天清晨极速抓取全球宏观经济指标、底层流动性数据、国际政经新闻以及重点城市气象信息。系统内置动态量化打分引擎（Z-Score & 动量）与大语言模型（LLM）翻译，最终将复杂的金融数据转化为直观的、带有操作建议的 Markdown / HTML 邮件研报发送给用户。

### 🚀 核心特性 (Key Features)
- **极限并发性能**：全链路采用 `concurrent.futures` 线程池调度，底层 TCP 连接池扩容至 100，将原本需 400 秒以上的 I/O 阻塞时间压缩至 **10~15 秒**。
- **动态量化引擎**：内置 Robust Z-Score 与 3 日动量一阶导算法，对实际利率、流动性水位、信用利差等进行动态解读，并输出美股 (VOO)、黄金 (18.HK)、大宗商品 (COPX) 的仓位风控建议。
- **大模型批量翻译**：接入 DeepSeek API，采用带序号的 Batch 处理策略合并翻译请求，大幅降低 Token 消耗与网络握手延迟。
- **高可用网络护城河**：具备多跳板穿透、Google Translate 降维代理（针对机构级 WAF）、多期限降级（针对 HIBOR 等场外断流数据）以及 429 智能指数退避重试机制。

### ⚡ 性能基准 (Performance Benchmarks)
针对 I/O 密集型任务的深度优化效果：
- **顺序执行模式**：约 420 - 450 秒。
- **当前并发架构**：**12 - 18 秒**（提速约 2500%）。
- **成本控制**：通过 Batch 翻译策略，API 调用成本降低了约 **65%**。

### 📈 量化决策矩阵 (Quantitative Logic)
系统基于概率分布进行结构化分析，拒绝单一因素推导：

| 维度 | 核心指标 (Factors) | 预警阈值 | 风险操作 (Actions) |
| :--- | :--- | :--- | :--- |
| **流动性** | HIBOR/LIBOR 息差, 逆回购规模 | Z > +2.0 | 缩减杠杆，警惕抽水 |
| **情绪面** | VIX 指数, 信用利差 | > 80th 分位 | 触发熔断，保留底仓 |
| **动量层** | 20D/200D 价格斜率 | 一阶导转负 | 动态减仓，观察支撑位 |

### 📂 核心文件架构说明 (Project Structure)

#### 1. `main.py` (主调度与渲染引擎)
系统的入口点。通过独立线程池同时唤醒三大核心模块，具备模块级容错能力。即使个别 API 宕机，也能确保其余数据正常汇总渲染。

#### 2. `macro.py` (宏观量化与动态研判引擎)
系统的金融大脑。并发抓取 FRED, Yahoo Finance, BOCHK 等 20+ 指标。抛弃枯燥数值，直接输出“🚨 离岸抽水”、“🌊 放水周期”等交易员视角的白话解读。

#### 3. `rss_parser.py` (政经新闻并发与智能翻译)
全局新闻监听。将“逐条翻译”重构为“打包编号翻译”，单网站仅调用一次 LLM API。利用精准正则表达式还原拆分，兼顾成本与速度。

#### 4. `weather.py` (智能气象与生活指数)
结合 Open-Meteo 数据，推算“Zone 2 户外运动”、“感冒风险”等六维生活建议，具备接口级降级策略。

#### 5. `http_client.py` (高可用网络底层)
连接池暴扩至 100，配置智能 429 熔断与指数退避重试，最大程度降低被 Cloudflare 等 WAF 拦截的概率。

### 🛠️ 自动化部署 (Deployment)
本项目完美适配 **GitHub Actions**，实现零成本每日推送：
1. Fork 本仓库。
2. 在 `Settings -> Secrets` 中配置 `SENDER_EMAIL`, `APP_PASSWORD`, `DEEPSEEK_API_KEY`, `FRED_API_KEY`。
3. 系统将根据 `.github/workflows/daily_brief.yml` 在北京时间每日早 7:00 自动运行。

---

<h2 id="english-version">🇺🇸 English Version</h2>

### 📖 Overview
An institutional-grade "Macro Quantitative Trading & Lifestyle Briefing System". It leverages a highly concurrent architecture to fetch global financial indicators, liquidity data, and geopolitical news within seconds. Using a dynamic Z-Score engine and LLM (DeepSeek) batch translation, it delivers actionable Markdown/HTML reports to your inbox every morning.

### 🚀 Key Features
- **Extreme Concurrency**: Powered by `concurrent.futures` and an expanded TCP pool (100 sessions), compressing 400s+ I/O tasks into **10~15s**.
- **Quant Intelligence**: Robust Z-Score & Momentum-based risk control for VOO, Gold, and COPX.
- **Cost-Effective LLM**: Batch-indexed translation strategy reducing token usage by 65%.
- **Network Resilience**: Multi-hop proxy support, Google Translate WAF-bypass, and smart 429 exponential backoff.

### 📈 Strategy & Risk Control
- **Liquidity**: Tracks HIBOR/LIBOR spreads and Reverse Repo levels.
- **Sentiment**: Monitors VIX and Credit Spreads for tail-risk hedging.
- **Technical**: 20D/200D slope analysis for momentum-based positioning.

### 📂 Architecture Highlights
1. **`main.py`**: Orchestrates modules with top-level fault tolerance.
2. **`macro.py`**: The "Financial Brain" fetching 20+ sources (FRED, LME, Yahoo).
3. **`rss_parser.py`**: Mass-parallel RSS scraping with regex-based LLM batch reconstruction.
4. **`weather.py`**: Custom outdoor lifestyle guidance (Zone 2 running, UV alerts).
5. **`http_client.py`**: Production-grade session management with connection pooling.

### ⚙️ Implementation Insights (For Delivery Engineers)
- **Robustness**: Handles heterogeneous data sources (JSON, RSS, HTML) with graceful degradation.
- **Efficiency**: Solves high-concurrency rate limiting (429) and WAF challenges.
- **Localization**: Implements context-aware LLM translation for cross-border information alignment.

---

### ⚠️ Disclaimer (免责声明)
1. **Non-Investment Advice**: All outputs are based on quantitative models and do not constitute financial advice.
2. **Data Latency**: Information from free APIs (Yahoo/FRED) may have 15-30 mins delay.
3. **Model Risk**: Z-Score models may fail during "Black Swan" events; always check live market data.

### ⚙️ Usage
```bash
# Clone the repository
git clone [https://github.com/your-username/macro-weather-briefing.git](https://github.com/your-username/macro-weather-briefing.git)
# Install dependencies
pip install -r requirements.txt
# Run the engine
python main.py
