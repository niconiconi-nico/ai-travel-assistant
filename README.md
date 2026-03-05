# Github团队协作规则：

1. 文件命名格式：
    - 所有文件都要使用下划线命名法（snake_case）
    - 例如：`google_flight_serpapi_test.py`
2. 测试文件命名格式：
    - 所有测试文件都要在 `tests/` 目录下
    - 测试文件名要以 `test_` 开头，后跟被测试的文件名
    - 例如：`test_google_flight_serpapi.py`

安装虚拟环境和依赖请参考Install_venv_and_dependencies.md

以下链接是指导如何操作github的：
https://github.com/firstcontributions/first-contributions/blob/main/docs/translations/README.zh-cn.md

很多API可以在https://serpapi.com/google-images-api 中获取

**提交文件时不要提交.env中的api_key!!!** 
请在本地环境变量中配置。

如有其他问题有待补充则后续补充

以下为GPT生成的内容：
---

# 🚀 一、基础协作规则（必须遵守）

---

## 1️⃣ 不要直接往 main 分支推代码

正确流程：

```
main  ← 稳定版本
  ↑
feature/xxx 分支开发
```

每个人：

```powershell
git checkout -b feature/add-flight-search
```

开发完：

```powershell
git push origin feature/add-flight-search
```

然后在 GitHub 上发 **Pull Request（PR）**

👉 审核通过再合并进 main。

这样可以避免：

- 覆盖别人代码
    
- 把 bug 直接带进主分支
    
- 项目崩掉
    

---

## 2️⃣ Commit 要小而清晰，且每写一个功能 commit 一次！

❌ 不要这样：

```
update
fix
修改代码
```

✅ 要这样：

```
add hotel recommendation module
fix weather api timeout issue
refactor agent workflow structure
```

规则：

- 一次 commit 只做一件事
    
- 信息写清楚改了什么
    

---

## 3️⃣ 永远 pull 再 push

每天开始工作前：

```powershell
git pull origin main
```

否则很容易：

- 冲突
    
- 覆盖别人代码
    

---

# 🧠 二、进阶团队规范（推荐）

---

## 4️⃣ 使用分支命名规范

推荐统一格式：

```
feature/功能名
fix/问题名
refactor/模块名
docs/文档更新
```

例如：

```
feature/ai-route-planner
fix/login-bug
```

项目一大，没有规范会非常混乱。

---

## 5️⃣ Pull Request 要写清楚

PR 描述应该写：

- 做了什么
    
- 为什么做
    
- 是否影响其他模块
    
- 测试结果
    

示例：

```
This PR adds flight search functionality using Amadeus API.
Tested with 5 sample routes.
No breaking changes.
```

---

## 6️⃣ Code Review 规则

团队里至少：

- 1 个人 review
    
- 才允许 merge
    

Review 关注：

- 是否有重复代码
    
- 是否影响现有逻辑
    
- 命名是否清晰
    
- 是否符合项目结构
    

这一步会极大提升项目质量。

---

# 📁 三、项目结构统一（非常重要）

你做 AI 旅游助手这类项目，建议结构：

```
ai-travel-assistant/
│
├── app/
│   ├── agent/
│   ├── tools/
│   ├── services/
│
├── tests/
├── requirements.txt
├── .gitignore
└── README.md
```

不要：

```
main.py
main2.py
test_new.py
final_version.py
final_version_v2.py
```

那是灾难 😄

---

# ⚠️ 四、绝对禁止的行为

- ❌ 不写 .gitignore
    
- ❌ 把 venv 提交上去
    
- ❌ 强制 push（git push -f）
    
- ❌ 直接改 main
    
- ❌ 不写 commit message
    


## 景点信息工具（Attraction Information Tool）

### 1) 环境变量配置
请在本地环境变量或 `.env` 中配置：

```bash
SERPAPI_API_KEY=your_serpapi_key
```

> 注意：不要提交真实 key 到仓库。

### 2) 工具位置与能力
- 文件：`app/tools/attraction_tool.py`
- 核心函数：`get_attraction_info(attraction_name: str, location: str | None = None) -> dict`
- 返回字段：
  - `name`
  - `image_url`
  - `opening_hours`
  - `visit_duration`
  - `ticket_price`
  - `sources`（至少保留 3 条可追溯来源）
- 搜索引擎：SerpAPI Google Search + Google Images
- 查询策略：
  - `{name} opening hours`
  - `{name} ticket price`
  - `{name} how long to spend`
  - `{name} official website`

### 3) 缓存说明
- 使用本地 JSON 缓存：`app/tools/attraction_cache.json`
- 相同景点与 location 的重复请求会直接命中缓存，减少 API 调用。

### 4) 运行最小 demo
```bash
python app/agents/attraction_demo.py
```

### 5) 与 Agent 集成
`app/agents/main_agent.py` 已注册 `attraction_information_tool`，Agent 在生成 itinerary 时可调用该工具补充：
- 营业时间
- 建议游玩时长
- 门票价格
- 图片链接与来源
