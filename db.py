import asyncio
import json
import os
from datetime import datetime, timezone

import asyncpg

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://copilot:copilot@localhost:5432/copilot_logger",
)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Session lifecycle ───────────────────────────────────────────

async def insert_session(
    session_id: str,
    developer: str,
    model: str | None = None,
    cwd: str | None = None,
    source: str | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO sessions (id, developer, model, cwd, source, started_at)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (id) DO NOTHING
        """,
        session_id,
        developer,
        model,
        cwd,
        source,
        _now(),
    )


async def update_session_end(
    session_id: str,
    end_reason: str | None = None,
    final_message: str | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE sessions
        SET ended_at = $2, end_reason = $3, final_message = $4
        WHERE id = $1
        """,
        session_id,
        _now(),
        end_reason,
        final_message,
    )


# ── Prompt logs ─────────────────────────────────────────────────

async def insert_prompt_log(
    session_id: str,
    prompt_text: str,
    response_text: str | None = None,
    duration_ms: int | None = None,
) -> str:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO prompt_logs (session_id, timestamp, prompt_text, response_text, duration_ms)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id
        """,
        session_id,
        _now(),
        prompt_text,
        response_text,
        duration_ms,
    )
    return str(row["id"])


async def update_prompt_response(
    prompt_id: str,
    response_text: str,
    duration_ms: int | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        UPDATE prompt_logs
        SET response_text = $2, duration_ms = $3
        WHERE id = $1
        """,
        prompt_id,
        response_text,
        duration_ms,
    )


# ── Tool logs ───────────────────────────────────────────────────

async def insert_tool_log(
    session_id: str,
    phase: str,
    tool_name: str,
    tool_args: dict | None = None,
    tool_result: dict | None = None,
    permission: str | None = None,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO tool_logs (session_id, timestamp, phase, tool_name, tool_args, tool_result, permission)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        session_id,
        _now(),
        phase,
        tool_name,
        json.dumps(tool_args) if tool_args else None,
        json.dumps(tool_result) if tool_result else None,
        permission,
    )


# ── Error logs ──────────────────────────────────────────────────

async def insert_error_log(
    session_id: str,
    error_message: str,
    error_context: str | None = None,
    recoverable: bool = False,
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO error_logs (session_id, timestamp, error_message, error_context, recoverable)
        VALUES ($1, $2, $3, $4, $5)
        """,
        session_id,
        _now(),
        error_message,
        error_context,
        recoverable,
    )
