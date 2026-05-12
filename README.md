# Hermes Web UI


基于 Web 的 [Hermes Agent](https://hermes-agent.nousresearch.com) 聊天界面。实时显示工具调用、思考过程、推理和流式响应 —— TUI 能展示的一切，在浏览器里也能看到。

## 特性

- 实时工具调用展示（可展开卡片）
- 流式 AI 响应 + Markdown 渲染
- 每个对话独立的 Agent 实例（上下文跨轮次保留）
- 多对话管理（创建、切换、删除）
- 上下文用量指示器

## 前置条件

- Python 3.10+
- [Hermes Agent](https://hermes-agent.nousresearch.com) 安装在 `~/.hermes/hermes-agent/`

## 快速启动

```bash
# 1. 克隆仓库
git clone https://github.com/swhje/hermes-web.git
cd hermes-web

# 2. 安装依赖
pip install fastapi uvicorn websockets pyyaml

# 3. 启动服务
python3 backend.py 3005

# 4. 打开浏览器
# http://127.0.0.1:3005
```

## 推荐：使用 Hermes 自带的 Python 环境

```bash
# 使用 Hermes 内置的 Python，避免依赖冲突
~/.hermes/hermes-agent/venv/bin/python3.11 backend.py 3005
```

### 端口

```bash
python3 backend.py 3005   # 默认
python3 backend.py 8080   # 自定义
```

服务会绑定到 `0.0.0.0`，局域网内可访问。

## 架构

```
浏览器 ──WebSocket── FastAPI 后端 ──imports── AIAgent（进程内）
                           │
                    ThreadPool（每个对话独立）
```

- 每个对话拥有独立的 `AIAgent` 实例
- Agent 运行在守护线程中，不阻塞 WebSocket
- 工具调用进度持久化到 `~/.hermes/hermes-web/conversations/` 的 JSON 文件
- 页面刷新后 WebSocket 重连，正在运行的 Agent 继续工作

## 项目结构

```
hermes-web/
├── backend.py           # FastAPI WebSocket 服务端
├── frontend/
│   └── index.html       # SPA 前端（单文件，无需构建工具）
└── README.md
```

## 说明

- 前端是单个 HTML 文件 —— 不需要 npm，不需要构建步骤
- 对话保存为 JSON 文件，存储在 `~/.hermes/hermes-web/conversations/`
- 默认最多保留 100 个对话（自动删除最旧的）

