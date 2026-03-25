import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_shared_session():
    session = requests.Session()

    # 【优化 1：增加 429 并发限流重试】
    # 高并发瞬间请求极易触发雅虎/FRED的 429 拦截，必须加入重试队列
    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504]
    )

    # 【优化 2：连接池暴扩（破除物理瓶颈）】
    # 默认 pool_maxsize=10。我们将其扩容到 50，确保 20+ 并发线程都有独立的 TCP 通道，无需排队
    adapter = HTTPAdapter(
        pool_connections=50,
        pool_maxsize=50,
        max_retries=retries
    )

    session.mount('http://', adapter)
    session.mount('https://', adapter)

    # 【优化 3：全局泛用性高潜装扮】
    # 融合了 HTML、XML 和 JSON 的高优权重，完美适配天气的 JSON 与 RSS 的 XML
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Referer": "https://www.google.com/",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive"
    })

    return session

# 暴露单例供其他模块引入
shared_session = create_shared_session()
