import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def create_shared_session():
    session = requests.Session()

    retries = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504]
    )

    # 【终极暴扩】：将连接池扩大到 100，支撑宏观(20)+天气(4)+RSS(50) 的全量瞬间并发
    adapter = HTTPAdapter(
        pool_connections=100,
        pool_maxsize=100,
        max_retries=retries
    )

    session.mount('http://', adapter)
    session.mount('https://', adapter)

    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Referer": "https://www.google.com/",
        "Cache-Control": "max-age=0",
        "Connection": "keep-alive"
    })

    return session

shared_session = create_shared_session()
