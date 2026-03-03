from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from tools import travel_planner, get_location_info, calculate_distance
load_dotenv()

def build_agent():
    """
    构建一个最简的 LangChain ReAct Agent：
    - 使用 gpt-4o-mini 作为推理模型
    - 注册旅行规划工具 travel_planner
    - 注册地图工具 get_location_info, calculate_distance
    - 使用中文提示词，明确输出结构
    """
    load_dotenv()  # 读取环境变量（如 OPENAI_API_KEY），无 .env 也不会报错
    provider = os.getenv("LLM_PROVIDER", "").lower()

    if provider == "google" or os.getenv("GOOGLE_API_KEY"):
        llm = ChatGoogleGenerativeAI(
            model=os.getenv("GOOGLE_LLM_MODEL"),
            api_key=os.getenv("GOOGLE_API_KEY"),
        )
    else:
        llm = ChatOpenAI(
            model=os.getenv("COMPANY_LLM_MODEL", "gpt-4o-mini"),
            base_url=os.getenv("COMPANY_BASE_URL"),
            api_key=os.getenv("COMPANY_API_KEY"),
        )

    prompt = (
        "你是一位专业旅行规划助理，拥有地图查询能力。"
        "当用户提出旅行需求时，请合理调用工具并按以下结构输出："
        "1）行程规划；2）每天安排；3）简要预算建议。"
        "如果涉及具体地点，可调用地图工具查询坐标或距离，并在回答中补充地理信息。"
    )

    # create_agent 是 LangChain 0.2+ 的新工厂方法，返回一个 CompiledStateGraph (LangGraph)
    agent = create_agent(llm, tools=[travel_planner, get_location_info, calculate_distance], system_prompt=prompt)
    return agent


def main() -> None:
    """
    简易命令行循环：
    - 输入旅行请求，返回规划结果
    - 可随时 Ctrl+C 退出
    """
    agent = build_agent()
    print("AI Travel Assistant 已启动，示例：我想去东京玩 3 天，预算 5000 RMB，喜欢美食和动漫")

    while True:
        try:
            user_input = input("旅行请求: ").strip()
            if not user_input:
                continue
            
            # 使用 LangGraph 风格的输入：messages 列表
            result = agent.invoke({"messages": [("user", user_input)]})
            
            # 提取最后一条 AI 消息的内容
            messages = result.get("messages", [])
            output = messages[-1].content if messages else "无回复"
            
            print("\n=== 旅行规划结果 ===")
            print(output)
            print("====================\n")
        except KeyboardInterrupt:
            print("\n已退出。")
            break
        except Exception as e:
            print(f"\n发生错误：{e}\n")


if __name__ == "__main__":
    main()
