import time
import concurrent.futures
from http_client import shared_session

def get_weather_description(code):
    weather_map = {
        0: "☀️ 晴朗", 1: "🌤️ 大部晴朗", 2: "⛅ 多云", 3: "☁️ 阴天",
        45: "🌫️ 雾", 48: "🌫️ 结霜浓雾", 51: "🌦️ 轻微毛毛雨", 53: "🌧️ 毛毛雨",
        55: "🌧️ 密集毛毛雨", 61: "🌧️ 小雨", 63: "🌧️ 中雨", 65: "🌧️ 大雨",
        71: "🌨️ 小雪", 73: "🌨️ 中雪", 75: "🌨️ 大雪", 95: "⛈️ 雷暴"
    }
    return weather_map.get(code, "☁️ 未知")

def process_single_city(city, coords):
    """处理单个城市的双接口抓取与数据解析（支持并发调用）"""
    w_url = f"https://api.open-meteo.com/v1/forecast?latitude={coords['lat']}&longitude={coords['lon']}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,visibility&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&timezone={coords['tz']}"
    aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={coords['lat']}&longitude={coords['lon']}&current=european_aqi&timezone={coords['tz']}"

    # 1. 独立抓取主气象数据 (强依赖)
    try:
        w_res = shared_session.get(w_url, timeout=10).json()
    except Exception:
        return f"| **{city}** | ⚠️ 气象接口超时 | - | - | - |\n"

    # 2. 独立抓取空气质量数据 (弱依赖，允许降级)
    try:
        aqi_res = shared_session.get(aqi_url, timeout=5).json()
        aqi_val = aqi_res.get('current', {}).get('european_aqi', 'N/A')
    except Exception:
        aqi_val = 'N/A'  # AQI 挂了不影响主体天气展示

    # 3. 安全解析与业务逻辑加工
    try:
        cur = w_res.get('current', {})
        daily = w_res.get('daily', {})

        # 安全提取当前数据
        atemp = cur.get('apparent_temperature', 20)
        code = cur.get('weather_code', 0)
        vis_km = cur.get('visibility', 10000) / 1000.0

        # 安全提取预测数据 (加上 [0] 防越界兜底)
        uv_list = daily.get('uv_index_max', [0])
        uv = uv_list[0] if uv_list and uv_list[0] is not None else 0
        t_max_list = daily.get('temperature_2m_max', [20])
        t_min_list = daily.get('temperature_2m_min', [10])
        t_max = t_max_list[0] if t_max_list else 20
        t_min = t_min_list[0] if t_min_list else 10
        temp_diff = t_max - t_min

        # 【生活建议计算】
        dress = "👕 清凉短袖" if atemp >= 28 else ("🧥 适宜薄外套" if atemp >= 18 else "🧣 注意保暖")
        sun = "🧴 无需防晒" if uv < 3 else "☀️ 建议防晒"

        is_aqi_good = isinstance(aqi_val, (int, float)) and aqi_val <= 100
        sport = "🏃 宜户外运动" if (is_aqi_good and code <= 2) else "🏠 建议室内"

        daily_codes = daily.get('weather_code', [0]*4)[:4]
        will_rain = any(c is not None and c >= 51 for c in daily_codes)
        car = "🚗 宜洗车" if not will_rain else "🚿 不宜洗车"
        umbrella = "☂️ 有雨带伞" if code >= 51 else "👓 无需带伞"
        cold = "🤒 较易感冒" if (temp_diff > 10 or atemp < 8) else "✅ 风险较低"

        # 【Markdown 排版组装】
        core = f"**{get_weather_description(code)}**<br>🌡️ {cur.get('temperature_2m', 'N/A')}°C<br>🌬️ {cur.get('wind_speed_10m', 'N/A')}km/h"
        outdoor = f"😷 AQI: {aqi_val}<br>☀️ UV: {uv}<br>👁️ {vis_km:.1f}km"
        advice = f"{dress}<br>{sun}<br>{sport}<br>{car}<br>{umbrella}<br>{cold}"

        # 组装未来三天趋势
        future = ""
        time_list = daily.get('time', [])
        for i in range(1, min(4, len(time_list))):
            d_code = daily_codes[i] if i < len(daily_codes) else 0
            d_desc = get_weather_description(d_code).split(' ')[0]
            d_min = t_min_list[i] if i < len(t_min_list) else "N/A"
            d_max = t_max_list[i] if i < len(t_max_list) else "N/A"
            d_time = time_list[i][-5:]
            future += f"• {d_time}: {d_desc} {d_min}~{d_max}°C<br>"

        return f"| **{city}** | {core} | {outdoor} | {advice} | {future} |\n"

    except Exception as e:
        return f"| **{city}** | ⚠️ 数据结构解析异常 | - | - | - |\n"


def fetch_weather_data(cities_config):
    """【主入口】多线程并发驱动"""
    weather_md = "## 🌤️ 重点城市今日天气与生活指数\n\n"
    weather_md += "| 城市 | 今日核心气象 | 户外指数 | 生活建议 (六项指标) | 未来三天趋势 |\n"
    weather_md += "| :--- | :--- | :--- | :--- | :--- |\n"

    print(f"🌤️ 天气模块：准备并发抓取 {len(cities_config)} 个城市数据...")

    # 使用最大 10 个线程并发查询所有城市
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # 将任务按顺序发射出去
        futures = {city: executor.submit(process_single_city, city, coords) for city, coords in cities_config.items()}

        # 严格按照传入配置的顺序读取结果
        for city in cities_config.keys():
            weather_md += futures[city].result()

    return weather_md + "\n---\n"
