"""
FastAPI server.

Patterns used:
  - lifespan      : creates DB tables on startup
  - Depends()     : injects DB session into routes
  - Pydantic      : validates request bodies
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Depends, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from dotenv import load_dotenv

load_dotenv()

from db.session import create_tables, get_session
from db.models import Report
from auth.auth import register, login, update_email, get_user_by_id, decode_token, AuthError
from core.cache import cache_stats, clear_cache
from core.research_manager import ResearchManager

STATIC_DIR = Path(__file__).parent

# job registry: job_id → {queue, status, pdf_bytes, ...}
_jobs: dict[str, dict] = {}


# ── Lifespan ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()   # create tables on startup if they don't exist
    yield

app = FastAPI(title="Deep Research", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Request schemas ───────────────────────────────────────────────────────
class RegisterBody(BaseModel):
    username: str
    email:    str
    password: str

class LoginBody(BaseModel):
    username: str
    password: str

class EmailBody(BaseModel):
    email: str

class ResearchBody(BaseModel):
    query:      str
    depth:      str  = "standard"
    send_email: bool = False
    export_pdf: bool = True


# ── Auth helper ───────────────────────────────────────────────────────────
def _get_token(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Authorization header missing.")
    payload = decode_token(authorization.split(" ", 1)[1])
    if not payload:
        raise AuthError("Invalid or expired token.")
    return payload


# ── Static ────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# ── Auth routes ───────────────────────────────────────────────────────────
@app.post("/api/auth/register")
async def api_register(body: RegisterBody, session: AsyncSession = Depends(get_session)):
    try:
        user  = await register(session, body.username, body.email, body.password)
        token = await login(session, body.username, body.password)
        return {"token": token, "user": {"id": user.id, "username": user.username, "email": user.email}}
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.post("/api/auth/login")
async def api_login(body: LoginBody, session: AsyncSession = Depends(get_session)):
    try:
        token   = await login(session, body.username, body.password)
        payload = decode_token(token)
        return {"token": token, "user": {"id": payload["sub"], "username": payload["username"], "email": payload["email"]}}
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)


@app.get("/api/auth/me")
async def api_me(authorization: str | None = Header(default=None),
                 session: AsyncSession = Depends(get_session)):
    try:
        payload = _get_token(authorization)
        user    = await get_user_by_id(session, payload["sub"])
        if not user:
            return JSONResponse({"error": "user not found"}, status_code=404)
        return {"id": user.id, "username": user.username, "email": user.email}
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)


@app.put("/api/auth/email")
async def api_update_email(body: EmailBody,
                           authorization: str | None = Header(default=None),
                           session: AsyncSession = Depends(get_session)):
    try:
        payload = _get_token(authorization)
        await update_email(session, payload["sub"], body.email)
        return {"ok": True, "email": body.email}
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=400)


# ── Research routes ───────────────────────────────────────────────────────
@app.post("/api/research")
async def start_research(body: ResearchBody,
                         authorization: str | None = Header(default=None)):
    try:
        user = _get_token(authorization)
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    if not body.query.strip():
        return JSONResponse({"error": "query is required"}, status_code=400)

    # Prune old jobs
    if len(_jobs) >= 100:
        oldest = min(_jobs, key=lambda k: _jobs[k]["started_at"])
        del _jobs[oldest]

    job_id = str(uuid.uuid4())
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    _jobs[job_id] = {
        "query":      body.query,
        "depth":      body.depth,
        "user_id":    user["sub"],
        "started_at": time.time(),
        "status":     "running",
        "queue":      queue,
        "pdf_bytes":  None,
    }

    async def _run():
        manager = ResearchManager()
        try:
            async for chunk in manager.run(
                query          = body.query,
                depth          = body.depth,
                send_email     = body.send_email,
                export_pdf_flag= body.export_pdf,
                recipient_email= user.get("email", ""),
                user_id        = user["sub"],
            ):
                await queue.put(chunk)
            if manager._last_pdf_bytes:
                _jobs[job_id]["pdf_bytes"] = manager._last_pdf_bytes
        except Exception as e:
            await queue.put(f"❌ Error: {e}")
        finally:
            _jobs[job_id]["status"] = "done"
            await queue.put(None)

    asyncio.create_task(_run())
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
async def stream_research(job_id: str, request: Request,
                          authorization: str | None = Header(default=None)):
    # EventSource can't set headers — accept token as query param too
    token_param = request.query_params.get("token")
    if not authorization and token_param:
        authorization = f"Bearer {token_param}"
    try:
        user = _get_token(authorization)
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    if job_id not in _jobs:
        return JSONResponse({"error": "job not found"}, status_code=404)
    if _jobs[job_id]["user_id"] != user["sub"]:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    queue: asyncio.Queue = _jobs[job_id]["queue"]

    async def event_gen() -> AsyncGenerator[str, None]:
        while True:
            chunk = await queue.get()
            if chunk is None:
                yield "event: done\ndata: {}\n\n"
                break
            yield f"data: {json.dumps({'text': chunk})}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/pdf/{job_id}")
async def download_pdf(job_id: str, authorization: str | None = Header(default=None)):
    try:
        user = _get_token(authorization)
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    if job_id not in _jobs:
        return JSONResponse({"error": "job not found"}, status_code=404)
    if _jobs[job_id]["user_id"] != user["sub"]:
        return JSONResponse({"error": "forbidden"}, status_code=403)

    pdf = _jobs[job_id].get("pdf_bytes")
    if not pdf:
        return JSONResponse({"error": "PDF not ready"}, status_code=404)

    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in _jobs[job_id]["query"][:50])
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="research_{safe}.pdf"'},
    )


# ── Report history routes ─────────────────────────────────────────────────
@app.get("/api/reports")
async def list_reports(authorization: str | None = Header(default=None),
                       session: AsyncSession = Depends(get_session)):
    try:
        user = _get_token(authorization)
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    result  = await session.execute(
        select(Report)
        .where(Report.user_id == user["sub"])
        .order_by(Report.created_at.desc())
    )
    reports = result.scalars().all()
    return [
        {"id": r.id, "query": r.query, "summary": r.summary,
         "word_count": r.word_count, "depth": r.depth, "created_at": r.created_at}
        for r in reports
    ]


@app.get("/api/reports/{report_id}")
async def fetch_report(report_id: str,
                       authorization: str | None = Header(default=None),
                       session: AsyncSession = Depends(get_session)):
    try:
        user = _get_token(authorization)
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    result = await session.execute(
        select(Report).where(Report.id == report_id, Report.user_id == user["sub"])
    )
    report = result.scalar_one_or_none()
    if not report:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"id": report.id, "query": report.query, "summary": report.summary,
            "markdown": report.markdown, "word_count": report.word_count,
            "depth": report.depth, "created_at": report.created_at}


@app.delete("/api/reports/{report_id}")
async def delete_report(report_id: str,
                        authorization: str | None = Header(default=None),
                        session: AsyncSession = Depends(get_session)):
    try:
        user = _get_token(authorization)
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)

    result = await session.execute(
        select(Report).where(Report.id == report_id, Report.user_id == user["sub"])
    )
    report = result.scalar_one_or_none()
    if not report:
        return JSONResponse({"error": "not found"}, status_code=404)
    await session.delete(report)
    await session.commit()
    return {"ok": True}


# ── Cache routes ──────────────────────────────────────────────────────────
@app.get("/api/cache/stats")
async def get_cache_stats(authorization: str | None = Header(default=None)):
    try:
        _get_token(authorization)
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)
    return cache_stats()


@app.post("/api/cache/clear")
async def clear_cache_endpoint(authorization: str | None = Header(default=None)):
    try:
        _get_token(authorization)
    except AuthError as e:
        return JSONResponse({"error": str(e)}, status_code=401)
    return {"cleared": clear_cache()}


# ── Entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)