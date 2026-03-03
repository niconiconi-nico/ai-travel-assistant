from langchain.tools import tool
import os
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from geopy.geocoders import Nominatim
from geopy.distance import geodesic


@tool
def get_location_info(place: str) -> str:
    """
    地图 API 工具：获取地点的详细地址与经纬度坐标
    - 输入：地名（如 "Tokyo Tower" 或 "东京塔"）
    - 输出：详细地址、纬度、经度
    """
    try:
        # 使用 Nominatim（OpenStreetMap）不需要 Key，但需要设置 user_agent
        geolocator = Nominatim(user_agent="ai_travel_agent")
        location = geolocator.geocode(place)
        
        if location:
            return f"地点：{place}\n地址：{location.address}\n坐标：({location.latitude}, {location.longitude})"
        else:
            return f"未找到地点：{place}，请尝试更具体的名称。"
    except Exception as e:
        return f"地图查询出错：{str(e)}"


@tool
def calculate_distance(place_a: str, place_b: str) -> str:
    """
    地图 API 工具：计算两个地点之间的直线距离（公里）
    - 输入：起始地、目的地
    - 输出：距离（km）
    """
    try:
        geolocator = Nominatim(user_agent="ai_travel_agent")
        loc_a = geolocator.geocode(place_a)
        loc_b = geolocator.geocode(place_b)
        
        if loc_a and loc_b:
            coords_a = (loc_a.latitude, loc_a.longitude)
            coords_b = (loc_b.latitude, loc_b.longitude)
            distance = geodesic(coords_a, coords_b).kilometers
            return f"{place_a} 与 {place_b} 的直线距离约为：{distance:.2f} 公里"
        else:
            return "无法找到其中一个地点的坐标，请检查地名。"
    except Exception as e:
        return f"距离计算出错：{str(e)}"


@tool
def travel_planner(query: str) -> str:
    """
    旅行规划工具：根据用户输入生成基础行程规划
    - 输入：目的地、天数、预算、偏好等
    - 输出：包含「行程规划」「每天安排」「简要预算建议」
    """
    provider = os.getenv("LLM_PROVIDER", "").lower()
    if provider == "google" or os.getenv("GOOGLE_API_KEY"):
        llm = ChatGoogleGenerativeAI(
            model=os.getenv("GOOGLE_LLM_MODEL", "gemini-1.5-flash"),
            api_key=os.getenv("GOOGLE_API_KEY"),
            temperature=0.2,
        )
    else:
        llm = ChatOpenAI(
            model=os.getenv("COMPANY_LLM_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("COMPANY_BASE_URL"),
            api_key=os.getenv("COMPANY_API_KEY"),
            temperature=0.2,
        )

    # 统一中文结构输出，便于阅读与后续扩展
    prompt = f"""
你是一位专业旅行规划师，请根据以下用户需求生成一个简洁易读的旅行方案：
用户需求：{query}

请严格按照以下中文结构输出：
1）行程规划
2）每天安排（按 Day 1/2/3... 列出：上午/下午/晚上）
3）简要预算建议（交通/住宿/餐饮/门票/购物）

要求：
- 结合用户偏好（美食/动漫/文化等）
- 预算给出区间或均值建议，并说明简单理由
"""
    return llm.invoke(prompt).content
