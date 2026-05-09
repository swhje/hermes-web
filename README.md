# Hermes Web UI

A web-based chat interface for [Hermes Agent](https://hermes-agent.nousresearch.com). Shows real-time tool calls, thinking, reasoning, and streaming responses — everything the CLI/TUI shows, in a clean browser UI.

## Features

- Real-time tool call display (expandable cards)
- Streaming assistant responses with markdown rendering
- Per-conversation agent instances (context preserved across turns)
- Multi-conversation management (create, switch, delete)
- Independent input buffer per conversation
- Context usage indicator
- Per-conversation stop button
- Dark/light theme ready
- Mobile responsive

## Screenshot

```
┌──────────────────────────────────────────────────┐
│ Hermes Agent                       ● 已连接  ⚙  │
├──────────────────────────────────────────────────┤
│                                                  │
│  🟢 查天气                           ✕           │
│     2分钟前 · 3条                                │
│  📄 介绍自己                        ✕           │
│     1小时前 · 2条                                │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ 武汉未来3天天气怎么样？                        │ │
│ │                                              │ │
│ │ D hermes-agent   2026-05-10 20:30:15          │ │
│ │ ┌──────────────────────────────────────────┐ │ │
│ │ │ ⚡ web_search  done                      │ │ │
│ │ │ 参数                                     │ │ │
│ │ │ { "query": "武汉 天气" }                  │ │ │
│ │ │ 结果                                     │ │ │
│ │ │ 武汉今天...明天...                        │ │ │
│ │ └──────────────────────────────────────────┘ │ │
│ │                                              │ │
│ │ 武汉未来三天以晴天为主，温度...                │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ deepseek-v4-flash 286/1M  █░░░░  0%              │
│ ┌──────────────────────────────────────────┐     │
│ │ 发送消息...                          ➤   │     │
│ └──────────────────────────────────────────┘     │
└──────────────────────────────────────────────────┘
```

## Prerequisites

- Python 3.10+
- [Hermes Agent](https://hermes-agent.nousresearch.com) installed at `~/.hermes/hermes-agent/`

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/446322065/hermes-web.git
cd hermes-web

# 2. Install dependencies
pip install fastapi uvicorn websockets pyyaml

# 3. Start the server
python3 backend.py 3005

# 4. Open in browser
# http://127.0.0.1:3005
```

## Start with Hermes venv (recommended)

```bash
# Use Hermes's bundled Python to avoid dependency issues
~/.hermes/hermes-agent/venv/bin/python3.11 backend.py 3005
```

## Configuration

### Model & Provider

Open the settings panel (⚙ icon in the top-right header) to configure:

| Field | Description | Example |
|-------|-------------|---------|
| Model | Model name | `deepseek-v4-flash` |
| Provider | API provider | `deepseek` |
| API 地址 | Custom API base URL | `https://api.deepseek.com/v1` |
| API 密钥 | API key | `sk-...` |
| 最大迭代 | Max tool-calling iterations | `60` |

By default, the backend inherits proxy settings (`HTTP_PROXY` / `HTTPS_PROXY`) from the terminal environment.

### Port

```bash
python3 backend.py 3005   # Default
python3 backend.py 8080   # Custom port
```

The server binds to `0.0.0.0` so it's accessible on your LAN.

## Architecture

```
Browser ──WebSocket── FastAPI Backend ──imports── AIAgent (in-process)
                           │
                    ThreadPool (per conversation)
```

- Each conversation gets its own `AIAgent` instance
- Agents run in daemon threads so they don't block the WebSocket
- Tool progress is persisted to JSON files at `~/.hermes/hermes-web/conversations/`
- Page refresh reconnects the WebSocket — running agents continue in the background

## Project Structure

```
hermes-web/
├── backend.py           # FastAPI WebSocket server
├── frontend/
│   └── index.html       # SPA frontend (single file, no build tools)
└── README.md
```

## Notes

- The frontend is a single HTML file — no npm, no build step
- Conversations are saved as JSON files in `~/.hermes/hermes-web/conversations/`
- Max 100 conversations by default (oldest auto-deleted)
- Works behind China's firewall if proxy is configured in the terminal
