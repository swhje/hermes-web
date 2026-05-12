#!/usr/bin/env python3
"""Hermes Web UI — Backend with conversation persistence"""
import asyncio
import json
import os
import sys
import threading
import uuid
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

# ── Hermes import ──────────────────────────────────
HERMES_HOME = os.path.expanduser("~/.hermes/hermes-agent")
sys.path.insert(0, HERMES_HOME)
sys.path.insert(0, os.path.join(HERMES_HOME, "venv/lib/python3.*/site-packages"))

for p in Path(HERMES_HOME, "venv").rglob("site-packages"):
    if p.is_dir():
        sys.path.insert(0, str(p))
        break

os.environ["HERMES_HOME"] = str(Path.home() / ".hermes")
os.environ["HERMES_DISABLE_TELEMETRY"] = "1"

from run_agent import AIAgent
from agent.model_metadata import get_model_context_length

import yaml

# ── Context estimation ────────────────────────────
def estimate_context_usage(messages, model_name="", base_url="", api_key="", provider=""):
    """Estimate token usage using Hermes's context length resolution."""
    total_chars = 0
    tool_chars = 0
    msg_count = 0
    for m in messages:
        content = m.get("content", "") or ""
        if isinstance(content, str):
            c = len(content)
            total_chars += c
            msg_count += 1
            if m.get("role") == "tool":
                tool_chars += c
    # Mixed Chinese/English/code: ~3 chars per token
    est_tokens = total_chars // 3

    # Use Hermes's built-in context length resolution (带缓存到 session.conv_config["_ctx_limit"]）
    limit = session.conv_config.get("_ctx_limit")
    if limit is None:
        limit = get_model_context_length(
            model=model_name,
            base_url=base_url or "",
            api_key=api_key or "",
            provider=provider or "",
        )
        session.conv_config["_ctx_limit"] = limit

    pct = round(est_tokens / limit * 100, 1)
    bar_len = 10
    filled = round(pct / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    return {
        "tokens": est_tokens,
        "limit": limit,
        "pct": pct,
        "bar": bar,
        "messages": msg_count,
        "tool_kb": round(tool_chars / 1024, 0),
    }

import yaml

# ── Config ─────────────────────────────────────────
config_path = Path.home() / ".hermes" / "config.yaml"
with open(config_path) as f:
    config = yaml.safe_load(f)

model_cfg = config.get("model", {})
default_model = model_cfg.get("default", "deepseek-v4-flash")
default_provider = model_cfg.get("provider", "deepseek")
default_base_url = model_cfg.get("base_url", "")
default_api_key = os.environ.get(model_cfg.get("env_key", "")) or ""

# ── Conversation storage ───────────────────────────
DATA_DIR = Path.home() / ".hermes" / "hermes-web"
CONV_DIR = DATA_DIR / "conversations"
CONV_DIR.mkdir(parents=True, exist_ok=True)


def load_conversations() -> List[dict]:
    """List all conversations (summary only), sorted by create time desc."""
    convs = []
    for f in CONV_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            convs.append({
                "id": data["id"],
                "title": data.get("title", "新对话"),
                "model": data.get("model", ""),
                "provider": data.get("provider", ""),
                "created_at": data.get("created_at", 0),
                "updated_at": data.get("updated_at", 0),
                "message_count": len(data.get("messages", [])),
                "tokens": sum(len((m.get("content","") or "")) for m in data.get("messages",[])) // 3,
                "has_agent": data["id"] in session.agents,
            })
        except Exception:
            pass
    convs.sort(key=lambda c: c["created_at"], reverse=True)
    return convs


def load_conversation(conv_id: str) -> Optional[dict]:
    path = CONV_DIR / f"{conv_id}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def save_conversation(data: dict):
    path = CONV_DIR / f"{data['id']}.json"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def delete_conversation(conv_id: str):
    path = CONV_DIR / f"{conv_id}.json"
    if path.exists():
        path.unlink()


MAX_CONVERSATIONS = 100


def create_conversation(model: str, provider: str) -> dict:
    # 超过上限则删除最早的
    convs = load_conversations()
    if len(convs) >= MAX_CONVERSATIONS:
        oldest = convs[-1]  # load_conversations 按 created_at 倒序，最后一个最老
        delete_conversation(oldest["id"])
    conv = {
        "id": str(uuid.uuid4()),
        "title": "新对话",
        "model": model,
        "provider": provider,
        "created_at": time.time(),
        "updated_at": time.time(),
        "messages": [],
    }
    save_conversation(conv)
    return conv


def add_message(conv_id: str, role: str, content: str, extra: dict = None):
    conv = load_conversation(conv_id)
    if not conv:
        return
    msg = {"role": role, "content": content, "timestamp": time.time()}
    if extra:
        msg.update(extra)
    conv["messages"].append(msg)
    conv["updated_at"] = time.time()
    # Auto-title from first user message
    if role == "user" and len(conv["messages"]) == 1:
        title = content.strip()[:60]
        if len(content.strip()) > 60:
            title += "…"
        conv["title"] = title
    save_conversation(conv)


def update_message(conv_id: str, tool_id: str, updates: dict):
    """Update an existing message by tool_id (for tool status updates)."""
    conv = load_conversation(conv_id)
    if not conv:
        return
    for msg in conv["messages"]:
        if msg.get("tool_id") == tool_id:
            msg.update(updates)
            msg["timestamp"] = time.time()
            break
    conv["updated_at"] = time.time()
    save_conversation(conv)


# ── FastAPI app ────────────────────────────────────
app = FastAPI(title="Hermes Web UI")


# ── REST API for conversations ─────────────────────
@app.get("/api/conversations")
async def list_conversations():
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=load_conversations(),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )


@app.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = load_conversation(conv_id)
    if not conv:
        return {"error": "not found"}, 404
    return conv


@app.delete("/api/conversations/{conv_id}")
async def remove_conversation(conv_id: str):
    delete_conversation(conv_id)
    # 如果删的是当前对话，重置 session 状态
    if session.conv_id == conv_id:
        session.conv_id = None
    return {"ok": True}


# ── WebSocket chat ──────────────────────────────────
class WsSession:
    """持久化会话状态，跨 WebSocket 重连存活。"""
    def __init__(self):
        self.ws: WebSocket | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.conv_id: Optional[str] = None
        self.conv_config: dict = {
            "model": default_model,
            "provider": default_provider,
            "base_url": default_base_url or None,
            "api_key": default_api_key or None,
            "max_iterations": 60,
        }
        self.reasoning_text: Dict[str, str] = {}  # conv_id -> accumulated reasoning
        self.thinking_text: Dict[str, str] = {}  # conv_id -> accumulated thinking
        self.stop_requested: bool = False
        self.agents: Dict[str, Any] = {}  # conv_id -> AIAgent
        self.conv_history: Dict[str, List[Dict]] = {}  # conv_id -> messages
        self.current_thread: threading.Thread | None = None

    async def send_event(self, event_type: str, **kwargs):
        """发事件到当前 WebSocket。"""
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send_json({"type": event_type, **kwargs})
        except Exception:
            pass


# 全局唯一 session，WS 重连不重置
session = WsSession()


@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    await ws.accept()
    # 更新 WS 引用 — 旧 agent 线程的 callback 会自动发到新连接
    session.ws = ws
    session.loop = asyncio.get_event_loop()
    # 不自动创建对话，等用户发消息或点新建才创建
    session.conv_id = None

    def make_callback(conv_id):
        def on_thinking(text: str):
            asyncio.run_coroutine_threadsafe(
                session.send_event("thinking", content=text, _conv_id=conv_id), session.loop
            )
            session.thinking_text[conv_id] = session.thinking_text.get(conv_id, "") + text

        def on_tool_start(tc_id: str, name: str, args: dict):
            asyncio.run_coroutine_threadsafe(
                session.send_event("tool_start", id=tc_id, name=name, args=args, _conv_id=conv_id), session.loop
            )
            # Persist tool start with accumulated reasoning
            if conv_id:
                reason_parts = []
                if session.thinking_text.get(conv_id):
                    reason_parts.append(session.thinking_text.get(conv_id, "").strip())
                if session.reasoning_text.get(conv_id):
                    reason_parts.append(session.reasoning_text.get(conv_id, "").strip())
                full_reasoning = "\n".join(reason_parts)
                session.reasoning_text[conv_id] = ""
                session.thinking_text[conv_id] = ""
                add_message(
                    conv_id, "tool", "",
                    extra={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "tool_args": args,
                        "tool_result": "",
                        "status": "running",
                        "reasoning": full_reasoning,
                    }
                )

        def on_tool_complete(tc_id: str, name: str, args: dict, result: str):
            result_str = str(result)
            if len(result_str) > 2000:
                result_str = result_str[:2000] + "\n... (truncated)"
            # Update persisted tool event first, then calc context
            if conv_id:
                update_message(conv_id, tc_id, {
                    "tool_result": result_str,
                    "status": "done",
                })
                # 每次工具完成重新计算上下文
                conv = load_conversation(conv_id)
                if conv:
                    ctx = estimate_context_usage(
                        conv.get("messages", []),
                        model_name=session.conv_config["model"],
                        base_url=session.conv_config.get("base_url", ""),
                        api_key=session.conv_config.get("api_key", ""),
                        provider=session.conv_config.get("provider", ""),
                    )
                else:
                    ctx = None
            else:
                ctx = None
            asyncio.run_coroutine_threadsafe(
                session.send_event("tool_complete", id=tc_id, name=name, result=result_str, context=ctx, _conv_id=conv_id), session.loop
            )

        def on_stream_delta(delta: str):
            if delta:
                asyncio.run_coroutine_threadsafe(
                    session.send_event("delta", content=delta, _conv_id=conv_id), session.loop
                )

        def on_reasoning(text: str):
            asyncio.run_coroutine_threadsafe(
                session.send_event("reasoning", content=text, _conv_id=conv_id), session.loop
            )
            session.reasoning_text[conv_id] = session.reasoning_text.get(conv_id, "") + text

        return on_thinking, on_tool_start, on_tool_complete, on_stream_delta, on_reasoning

    # Send initial config + conversation ID
    await session.send_event("config_loaded", conv_id=session.conv_id, **session.conv_config)

    try:
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type", "message")

            # ── Config update ──
            if msg_type == "configure":
                for key in ("model", "provider", "max_iterations"):
                    if key in data:
                        session.conv_config[key] = data[key]
                if "base_url" in data:
                    session.conv_config["base_url"] = data["base_url"] or None
                if "api_key" in data:
                    session.conv_config["api_key"] = data["api_key"] or None
                await session.send_event("config_loaded", conv_id=session.conv_id, **session.conv_config)
                continue

            # ── New chat ──
            if msg_type == "new_chat":
                session.conv_id = create_conversation(
                    session.conv_config["model"], session.conv_config["provider"]
                )["id"]
                await session.send_event("config_loaded", conv_id=session.conv_id, **session.conv_config)
                continue

            # ── Switch to existing conversation ──
            if msg_type == "switch_chat":
                conv_id = data.get("conv_id", "")
                conv = load_conversation(conv_id)
                if conv:
                    session.conv_id = conv_id
                    # 上下文用量只跟实际 agent 实例绑定，没有 agent 就不显示
                    has_agent = conv_id in session.agents
                    if has_agent and session.conv_history.get(conv_id):
                        ctx = estimate_context_usage(
                            session.conv_history[conv_id],
                            model_name=session.conv_config["model"],
                            base_url=session.conv_config.get("base_url", ""),
                            api_key=session.conv_config.get("api_key", ""),
                            provider=session.conv_config.get("provider", ""),
                        )
                    else:
                        ctx = None
                    # 前端显示始终用保存的消息格式，不用 conv_history（含 system/tool_call 块）
                    await session.send_event("load_conversation", messages=conv.get("messages", []), context=ctx, _conv_id=conv_id)
                continue

            # ── Stop processing ──
            if msg_type == "stop":
                session.stop_requested = True
                # 中断当前对话的 agent 执行（类似 TUI 的 /stop）
                agent = session.agents.get(session.conv_id)
                if agent:
                    try:
                        agent.interrupt()
                    except Exception:
                        pass
                await session.send_event("stopped", _conv_id=session.conv_id)
                continue

            # ── Chat message ──
            message = data.get("message", "").strip()
            if not message:
                continue

            # 如果没有对话，自动创建
            if not session.conv_id:
                conv = create_conversation(
                    session.conv_config["model"], session.conv_config["provider"]
                )
                session.conv_id = conv["id"]
                await session.send_event("config_loaded", conv_id=session.conv_id, **session.conv_config)

            # Save user message
            add_message(session.conv_id, "user", message)

            await session.send_event("user_message", content=message, _conv_id=session.conv_id)

            # 每个对话复用同一个 AIAgent，保持上下文
            agent = session.agents.get(session.conv_id)
            if agent is None:
                conv_id_for_agent = session.conv_id
                on_thinking, on_tool_start, on_tool_complete, on_stream_delta, on_reasoning = \
                    make_callback(conv_id_for_agent)

                agent = AIAgent(
                    model=session.conv_config["model"],
                    provider=session.conv_config["provider"],
                    base_url=session.conv_config["base_url"],
                    api_key=session.conv_config["api_key"],
                    quiet_mode=True,
                    tool_start_callback=on_tool_start,
                    tool_complete_callback=on_tool_complete,
                    stream_delta_callback=on_stream_delta,
                    thinking_callback=on_thinking,
                    reasoning_callback=on_reasoning,
                    max_iterations=session.conv_config["max_iterations"],
                )
                session.agents[session.conv_id] = agent

            def run(conv_id: str):
                try:
                    history = session.conv_history.get(conv_id)
                    result = agent.run_conversation(
                        message,
                        conversation_history=history,
                    )
                    if session.stop_requested:
                        return
                    # 保存本轮完整消息列表，供下一轮作为历史
                    session.conv_history[conv_id] = result.get("messages", [])
                    final = result.get("final_response", "") or ""
                    # Save assistant response
                    add_message(conv_id, "assistant", final)
                    # Clear reasoning for next round
                    session.reasoning_text[conv_id] = ""
                    session.thinking_text[conv_id] = ""
                    # 计算上下文用量
                    ctx = estimate_context_usage(
                        session.conv_history[conv_id],
                        model_name=session.conv_config["model"],
                        base_url=session.conv_config.get("base_url", ""),
                        api_key=session.conv_config.get("api_key", ""),
                        provider=session.conv_config.get("provider", ""),
                    )
                    asyncio.run_coroutine_threadsafe(
                        session.send_event("done", content=final, context=ctx, _conv_id=conv_id_for_thread), session.loop
                    )
                except Exception as e:
                    if session.stop_requested:
                        return
                    asyncio.run_coroutine_threadsafe(
                        session.send_event("error", message=str(e), _conv_id=conv_id_for_thread), session.loop
                    )

            conv_id_for_thread = session.conv_id
            session.stop_requested = False
            thread = threading.Thread(target=run, args=(conv_id_for_thread,), daemon=True)
            session.current_thread = thread
            thread.start()

            # 不阻塞主循环 — 后台监视线程完成，主循环继续接收消息
            async def _wait_thread():
                while thread.is_alive() and not session.stop_requested:
                    await asyncio.sleep(0.1)
                if not session.stop_requested:
                    await session.send_event("end", _conv_id=conv_id_for_thread)

            asyncio.create_task(_wait_thread())

    except WebSocketDisconnect:
        # WS 断开不杀线程 — 重连后续上
        pass
    except Exception as e:
        try:
            await session.send_event("error", message=str(e))
        except Exception:
            pass


# ── Static files ────────────────────────────────────
FRONTEND_DIR = Path(__file__).parent / "frontend"
FRONTEND_DIR.mkdir(exist_ok=True)


@app.get("/")
async def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/{path:path}")
async def static_files(path: str):
    file = FRONTEND_DIR / path
    if file.exists() and file.is_file():
        return FileResponse(str(file))
    return FileResponse(str(FRONTEND_DIR / "index.html"))


# ── Main ────────────────────────────────────────────
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 3005
    print(f"\n  Hermes Web UI → http://0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
