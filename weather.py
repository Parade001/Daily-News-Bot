import time
from http_client import shared_session

def get_weather_description(code):
    weather_map = {
        0: "☀️ 晴朗", 1: "🌤️ 大部晴朗", 2: "⛅ 多云", 3: "☁️ 阴天",
        45: "🌫️ 雾", 48: "🌫️ 结霜浓雾", 51: "🌦️ 轻微毛毛雨", 53: "🌧️ 毛毛雨",
        55: "🌧️ 密集毛毛雨", 61: "🌧️ 小雨", 63: "🌧️ 中雨", 65: "🌧️ 大雨",
        71: "🌨️ 小雪", 73: "🌨️ 中雪", 75: "🌨️ 大雪", 95: "⛈️ 雷暴"
    }
    return weather_map.get(code, "☁️ 未知")

def fetch_weather_data(cities_config):
    weather_md = "## 🌤️ 重点城市今日天气与生活指数\n\n"
    weather_md += "| 城市 | 今日核心气象 | 户外指数 | 生活建议 (六项指标) | 未来三天趋势 |\n"
    weather_md += "| :--- | :--- | :--- | :--- | :--- |\n"

    for city, coords in cities_config.items():
        try:
            w_url = f"https://api.open-meteo.com/v1/forecast?latitude={coords['lat']}&longitude={coords['lon']}&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m,visibility&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max&timezone={coords['tz']}"
            aqi_url = f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={coords['lat']}&longitude={coords['lon']}&current=european_aqi&timezone={coords['tz']}"

            w_res = shared_session.get(w_url, timeout=15).json()
            aqi_res = shared_session.get(aqi_url, timeout=15).json()

            cur = w_res['current']
            daily = w_res['daily']
            aqi_val = aqi_res.get('current', {}).get('european_aqi', 'N/A')

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
