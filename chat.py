"""
Copilot Chat Logger — Terminal MVP
Wraps the GitHub Copilot SDK with audit hooks that log every interaction to PostgreSQL.

Usage:
    python chat.py                      # uses logged-in Copilot CLI user
    python chat.py --model gpt-4.1      # specify model
    python chat.py --developer alice     # override developer name
"""

import argparse
import asyncio
import json
import os
import sys
import time
import uuid

from copilot import CopilotClient
from copilot.generated.session_events import SessionEventType

import db

# ── State shared across hooks ───────────────────────────────────

_session_id: str = str(uuid.uuid4())
_developer: str = os.environ.get("USER", "unknown")
_current_prompt_id: str | None = None
_prompt_start: float = 0.0
_response_chunks: list[str] = []
_prompt_count: int = 0
_model: str = "gpt-4o"


# ── Hook handlers ───────────────────────────────────────────────

async def _ensure_session(invocation):
    """Ensure session row exists (hooks fire in unpredictable order)."""
    global _session_id
    sid = invocation["session_id"]
    if sid != _session_id:
        _session_id = sid
        await db.insert_session(
            session_id=_session_id,
            developer=_developer,
            model=_model,
            cwd=os.getcwd(),
            source="new",
        )


async def on_session_start(input_data, invocation):
    await _ensure_session(invocation)
    # Update with richer data from the hook
    source = input_data.get("source", "new")
    cwd = input_data.get("cwd", os.getcwd())
    pool = await db.get_pool()
    await pool.execute(
        "UPDATE sessions SET source = $2, cwd = $3 WHERE id = $1",
        _session_id, source, cwd,
    )
    return None


async def on_user_prompt_submitted(input_data, invocation):
    global _current_prompt_id, _prompt_start, _response_chunks, _prompt_count
    await _ensure_session(invocation)
    prompt = input_data["prompt"]
    _prompt_start = time.time()
    _response_chunks = []
    _prompt_count += 1
    _current_prompt_id = await db.insert_prompt_log(
        session_id=_session_id,
        prompt_text=prompt,
    )
    return None  # pass through unchanged


async def on_pre_tool_use(input_data, invocation):
    await _ensure_session(invocation)
    tool_name = input_data.get("toolName", "unknown")
    tool_args = input_data.get("toolArgs")
    await db.insert_tool_log(
        session_id=_session_id,
        phase="pre",
        tool_name=tool_name,
        tool_args=tool_args if isinstance(tool_args, dict) else None,
        permission="allow",
    )
    return {"permissionDecision": "allow"}


async def on_post_tool_use(input_data, invocation):
    await _ensure_session(invocation)
    tool_name = input_data.get("toolName", "unknown")
    tool_args = input_data.get("toolArgs")
    tool_result = input_data.get("toolResult")
    result_dict = None
    if isinstance(tool_result, dict):
        result_dict = tool_result
    elif tool_result is not None:
        result_dict = {"value": str(tool_result)[:2000]}
    await db.insert_tool_log(
        session_id=_session_id,
        phase="post",
        tool_name=tool_name,
        tool_args=tool_args if isinstance(tool_args, dict) else None,
        tool_result=result_dict,
    )
    return None


async def on_error_occurred(input_data, invocation):
    await _ensure_session(invocation)
    await db.insert_error_log(
        session_id=_session_id,
        error_message=input_data.get("error", "unknown error"),
        error_context=input_data.get("errorContext"),
        recoverable=input_data.get("recoverable", False),
    )
    return None


async def on_session_end(input_data, invocation):
    await _ensure_session(invocation)
    reason = input_data.get("reason", "complete")
    final_msg = input_data.get("finalMessage")
    await db.update_session_end(
        session_id=_session_id,
        end_reason=reason,
        final_message=final_msg,
    )
    return None


# ── Main interactive loop ───────────────────────────────────────

async def main():
    global _developer, _current_prompt_id, _response_chunks

    parser = argparse.ArgumentParser(description="Copilot Chat Logger")
    parser.add_argument("--model", default="gpt-4o", help="Model to use (default: gpt-4o)")
    parser.add_argument("--developer", default=None, help="Developer name (default: $USER)")
    args = parser.parse_args()

    if args.developer:
        _developer = args.developer

    global _model
    _model = args.model

    # Connect to database
    try:
        await db.get_pool()
    except Exception as e:
        print(f"\n❌ Cannot connect to database: {e}")
        print("   Make sure PostgreSQL is running: docker compose up db -d")
        sys.exit(1)

    # Start Copilot SDK client
    client = CopilotClient()
    await client.start()

    session = await client.create_session({
        "model": args.model,
        "streaming": True,
        "hooks": {
            "on_session_start": on_session_start,
            "on_user_prompt_submitted": on_user_prompt_submitted,
            "on_pre_tool_use": on_pre_tool_use,
            "on_post_tool_use": on_post_tool_use,
            "on_error_occurred": on_error_occurred,
            "on_session_end": on_session_end,
        },
    })

    # Stream response tokens to terminal
    async def flush_response():
        """Save accumulated response chunks to the database."""
        global _current_prompt_id, _response_chunks
        if _current_prompt_id and _response_chunks:
            full_response = "".join(_response_chunks)
            duration = int((time.time() - _prompt_start) * 1000)
            await db.update_prompt_response(
                prompt_id=_current_prompt_id,
                response_text=full_response,
                duration_ms=duration,
            )

    def handle_event(event):
        if event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
            delta = event.data.delta_content
            if delta:
                sys.stdout.write(delta)
                sys.stdout.flush()
                _response_chunks.append(delta)
        elif event.type == SessionEventType.SESSION_IDLE:
            print()  # newline after streamed response

    session.on(handle_event)

    print("🤖 Copilot Chat (logged session)")
    print(f"   Developer: {_developer}")
    print(f"   Model:     {args.model}")
    print(f"   Session:   {_session_id[:8]}...")
    print("   Type 'exit' to quit\n")

    try:
        while True:
            try:
                user_input = input("You: ")
            except EOFError:
                break

            if user_input.strip().lower() in ("exit", "quit", "q"):
                break

            if not user_input.strip():
                continue

            sys.stdout.write("Copilot: ")
            await session.send_and_wait({"prompt": user_input})
            await flush_response()
            print()  # extra blank line between turns
    except KeyboardInterrupt:
        print("\n")
    finally:
        # Always clean up to avoid orphan copilot processes
        try:
            await client.stop()
        except Exception:
            pass
        try:
            await db.close_pool()
        except Exception:
            pass

    print(f"Session ended. {_prompt_count} prompt(s) logged.")


if __name__ == "__main__":
    asyncio.run(main())
