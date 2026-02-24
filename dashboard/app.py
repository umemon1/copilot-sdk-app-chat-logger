"""
Copilot Chat Logger — PM Dashboard
FastAPI app serving a web dashboard to view logged Copilot Chat sessions.
"""

import os
from datetime import datetime, timezone

import asyncpg
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://copilot:copilot@localhost:5432/copilot_logger",
)

app = FastAPI(title="Copilot Chat Logger Dashboard")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

pool: asyncpg.Pool | None = None


@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)


@app.on_event("shutdown")
async def shutdown():
    if pool:
        await pool.close()


# ── Dashboard Pages ─────────────────────────────────────────────


@app.get("/dashboard/", response_class=HTMLResponse)
async def sessions_list(
    request: Request,
    developer: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
):
    offset = (page - 1) * per_page
    conditions = []
    params: list = []

    if developer:
        conditions.append(f"s.developer = ${len(params) + 1}")
        params.append(developer)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Total count
    count_row = await pool.fetchrow(
        f"SELECT COUNT(*) as total FROM sessions s {where}", *params,
    )
    total = count_row["total"]

    # Sessions with prompt count
    rows = await pool.fetch(
        f"""
        SELECT s.*,
               COUNT(p.id) AS prompt_count,
               (SELECT LEFT(p2.prompt_text, 120) FROM prompt_logs p2
                WHERE p2.session_id = s.id ORDER BY p2.timestamp LIMIT 1) AS first_prompt
        FROM sessions s
        LEFT JOIN prompt_logs p ON p.session_id = s.id
        {where}
        GROUP BY s.id
        ORDER BY s.started_at DESC
        LIMIT ${len(params) + 1} OFFSET ${len(params) + 2}
        """,
        *params, per_page, offset,
    )

    # Developers for filter dropdown
    devs = await pool.fetch("SELECT DISTINCT developer FROM sessions ORDER BY developer")

    # Stats
    stats = await pool.fetchrow("""
        SELECT
            COUNT(DISTINCT s.id) AS total_sessions,
            COUNT(DISTINCT s.developer) AS unique_devs,
            COUNT(p.id) AS total_prompts,
            COALESCE(AVG(p.duration_ms), 0)::int AS avg_duration_ms
        FROM sessions s
        LEFT JOIN prompt_logs p ON p.session_id = s.id
    """)

    return templates.TemplateResponse("sessions.html", {
        "request": request,
        "sessions": rows,
        "developers": [r["developer"] for r in devs],
        "selected_developer": developer,
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "stats": stats,
    })


@app.get("/dashboard/sessions/{session_id}", response_class=HTMLResponse)
async def session_detail(request: Request, session_id: str):
    session = await pool.fetchrow("SELECT * FROM sessions WHERE id = $1", session_id)
    if not session:
        return HTMLResponse("<h1>Session not found</h1>", status_code=404)

    prompts = await pool.fetch(
        "SELECT * FROM prompt_logs WHERE session_id = $1 ORDER BY timestamp", session_id,
    )
    tools = await pool.fetch(
        "SELECT * FROM tool_logs WHERE session_id = $1 ORDER BY timestamp", session_id,
    )
    errors = await pool.fetch(
        "SELECT * FROM error_logs WHERE session_id = $1 ORDER BY timestamp", session_id,
    )

    return templates.TemplateResponse("detail.html", {
        "request": request,
        "session": session,
        "prompts": prompts,
        "tools": tools,
        "errors": errors,
    })


# ── Log Ingestion API (for future VS Code extension) ───────────

@app.post("/api/logs")
async def ingest_logs(request: Request):
    data = await request.json()
    event_type = data.get("type")
    payload = data.get("payload", {})
    session_id = data.get("session_id")

    if event_type == "session_start":
        await pool.execute(
            """INSERT INTO sessions (id, developer, model, cwd, source, started_at)
               VALUES ($1, $2, $3, $4, $5, NOW())
               ON CONFLICT (id) DO NOTHING""",
            session_id, payload.get("developer"), payload.get("model"),
            payload.get("cwd"), payload.get("source"),
        )
    elif event_type == "prompt":
        await pool.execute(
            """INSERT INTO prompt_logs (session_id, prompt_text, response_text, duration_ms)
               VALUES ($1, $2, $3, $4)""",
            session_id, payload.get("prompt_text"),
            payload.get("response_text"), payload.get("duration_ms"),
        )
    elif event_type == "tool":
        import json
        await pool.execute(
            """INSERT INTO tool_logs (session_id, phase, tool_name, tool_args, tool_result, permission)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            session_id, payload.get("phase"), payload.get("tool_name"),
            json.dumps(payload.get("tool_args")) if payload.get("tool_args") else None,
            json.dumps(payload.get("tool_result")) if payload.get("tool_result") else None,
            payload.get("permission"),
        )
    elif event_type == "error":
        await pool.execute(
            """INSERT INTO error_logs (session_id, error_message, error_context, recoverable)
               VALUES ($1, $2, $3, $4)""",
            session_id, payload.get("error_message"),
            payload.get("error_context"), payload.get("recoverable", False),
        )
    elif event_type == "session_end":
        await pool.execute(
            """UPDATE sessions SET ended_at = NOW(), end_reason = $2, final_message = $3
               WHERE id = $1""",
            session_id, payload.get("end_reason"), payload.get("final_message"),
        )

    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8081)
