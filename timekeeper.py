#!/usr/bin/env python3
"""
OpenClaw Timekeeper — current time, task tracking, wakeup pings, web UI.

REST API at /api/*, web UI served at /. Default bind 127.0.0.1:7779.
Wakeups are delivered to clawd via Telegram so his telegram extension
picks them up and prompts him to respond.
"""
import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ─── PATHS ────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
UI_DIR = SCRIPT_DIR / "ui"

BASE = Path.home() / ".openclaw" / "timekeeper"
DB = BASE / "db"
LOG = BASE / "log"
CONFIG_FILE = BASE / "config.json"
TASKS_FILE = DB / "tasks.json"
WAKEUPS_FILE = DB / "wakeups.json"
HISTORY_FILE = DB / "history.json"

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 7779,
    "timezone": "Australia/Sydney",
    "telegram_bot_token": "",
    "telegram_chat_id": "",
    "wakeup_check_interval_seconds": 2,
    "default_task_ttl_seconds": 3600,
    "max_history": 500,
    "wakeup_message_prefix": "[TIMEKEEPER WAKEUP]",
}

START_TIME = time.time()


# ─── STORAGE ──────────────────────────────────────────────
def _ensure_dirs():
    for d in [BASE, DB, LOG]:
        d.mkdir(parents=True, exist_ok=True)


def _log(msg: str):
    try:
        with open(LOG / "daemon.log", "a") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except Exception:
        pass


def _load_config() -> dict:
    _ensure_dirs()
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        return dict(DEFAULT_CONFIG)
    cfg = json.loads(CONFIG_FILE.read_text())
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def _save_config():
    CONFIG_FILE.write_text(json.dumps(CONFIG, indent=2))


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2))


def _append_history(entry: dict):
    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text())
        except Exception:
            history = []
    history.append(entry)
    history = history[-int(CONFIG.get("max_history", 500)):]
    HISTORY_FILE.write_text(json.dumps(history, indent=2))


# ─── TIME HELPERS ─────────────────────────────────────────
def _tz():
    name = CONFIG.get("timezone")
    if not name:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def _now() -> datetime:
    return datetime.now(tz=_tz())


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ─── TELEGRAM ─────────────────────────────────────────────
async def send_telegram(text: str) -> dict:
    token = CONFIG.get("telegram_bot_token", "")
    chat_id = CONFIG.get("telegram_chat_id", "")
    if not token or not chat_id:
        return {"sent": False, "reason": "telegram_not_configured"}
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json={"chat_id": chat_id, "text": text})
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text}
            ok = r.status_code == 200 and isinstance(body, dict) and body.get("ok", False)
            return {"sent": ok, "status_code": r.status_code, "response": body}
    except Exception as e:
        _log(f"telegram send failed: {e}")
        return {"sent": False, "reason": str(e)}


# ─── MODELS ───────────────────────────────────────────────
class StartTaskBody(BaseModel):
    name: str
    description: Optional[str] = None
    ttl_seconds: Optional[int] = None
    expected_duration_seconds: Optional[int] = None


class HeartbeatBody(BaseModel):
    progress_note: Optional[str] = None
    extend_ttl_seconds: Optional[int] = None


class CompleteTaskBody(BaseModel):
    result: Optional[str] = None
    note: Optional[str] = None


class ScheduleWakeupBody(BaseModel):
    in_seconds: int = Field(..., ge=1)
    message: str
    task_id: Optional[str] = None


# ─── STATE ────────────────────────────────────────────────
CONFIG = _load_config()
TASKS = _load_json(TASKS_FILE)
WAKEUPS = _load_json(WAKEUPS_FILE)


# ─── BACKGROUND SCHEDULER ─────────────────────────────────
async def scheduler_loop():
    interval = max(1, int(CONFIG.get("wakeup_check_interval_seconds", 2)))
    _log(f"scheduler started, interval={interval}s")
    while True:
        try:
            now_ts = int(time.time())
            due = [
                w for w in list(WAKEUPS.values())
                if not w.get("fired") and w.get("fire_at_unix", 0) <= now_ts
            ]
            for w in due:
                task_label = ""
                tid = w.get("task_id")
                if tid and tid in TASKS:
                    task_label = f"\nTask: {TASKS[tid].get('name', '')}"
                text = (
                    f"{CONFIG.get('wakeup_message_prefix', '[TIMEKEEPER WAKEUP]')}"
                    f"{task_label}\n"
                    f"Message: {w.get('message', '')}\n"
                    f"Time: {_iso(_now())}\n"
                    f"Wakeup ID: {w['id']}\n"
                    f"(reply to this to continue work)"
                )
                send_result = await send_telegram(text)
                w["fired"] = True
                w["fired_at"] = _iso(_now())
                w["send_result"] = send_result
                _append_history({
                    "event": "wakeup_fired",
                    "wakeup_id": w["id"],
                    "message": w.get("message"),
                    "at": _iso(_now()),
                    "telegram_sent": send_result.get("sent"),
                })
                _log(f"wakeup {w['id']} fired, telegram_sent={send_result.get('sent')}")
            if due:
                _save_json(WAKEUPS_FILE, WAKEUPS)
        except Exception as e:
            _log(f"scheduler error: {e}")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_dirs()
    _log("timekeeper starting up")
    task = asyncio.create_task(scheduler_loop())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        _save_json(TASKS_FILE, TASKS)
        _save_json(WAKEUPS_FILE, WAKEUPS)
        _log("timekeeper shut down")


app = FastAPI(title="OpenClaw Timekeeper", lifespan=lifespan)


# ─── REST API ─────────────────────────────────────────────
@app.get("/api/status")
def api_status():
    return {
        "ok": True,
        "uptime_seconds": int(time.time() - START_TIME),
        "active_tasks": sum(1 for t in TASKS.values() if t.get("status") == "active"),
        "total_tasks": len(TASKS),
        "pending_wakeups": sum(1 for w in WAKEUPS.values() if not w.get("fired")),
        "telegram_configured": bool(
            CONFIG.get("telegram_bot_token") and CONFIG.get("telegram_chat_id")
        ),
        "timezone": CONFIG.get("timezone"),
    }


@app.get("/api/time")
def api_time():
    now = _now()
    return {
        "iso": _iso(now),
        "unix": int(now.timestamp()),
        "date": now.strftime("%Y-%m-%d"),
        "time_24h": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "timezone": str(now.tzinfo),
        "uptime_seconds": int(time.time() - START_TIME),
    }


@app.post("/api/tasks")
def api_start_task(body: StartTaskBody):
    tid = uuid.uuid4().hex[:8]
    now = _now()
    ttl = body.ttl_seconds or CONFIG.get("default_task_ttl_seconds", 3600)
    task = {
        "id": tid,
        "name": body.name,
        "description": body.description,
        "started_at": _iso(now),
        "started_at_unix": int(now.timestamp()),
        "ttl_seconds": int(ttl),
        "expected_duration_seconds": body.expected_duration_seconds,
        "last_heartbeat": _iso(now),
        "last_heartbeat_unix": int(now.timestamp()),
        "progress_notes": [],
        "status": "active",
    }
    TASKS[tid] = task
    _save_json(TASKS_FILE, TASKS)
    _append_history({"event": "task_started", "task_id": tid, "name": body.name, "at": _iso(now)})
    return task


@app.get("/api/tasks")
def api_list_tasks(status: str = "active"):
    items = list(TASKS.values())
    if status != "all":
        items = [t for t in items if t.get("status") == status]
    now_ts = time.time()
    out = []
    for t in items:
        e = dict(t)
        e["elapsed_seconds"] = int(now_ts - t.get("started_at_unix", now_ts))
        if t.get("status") == "active":
            since_hb = int(now_ts - t.get("last_heartbeat_unix", now_ts))
            e["seconds_since_heartbeat"] = since_hb
            e["seconds_until_ttl"] = max(0, int(t.get("ttl_seconds", 0)) - since_hb)
        out.append(e)
    return {"count": len(out), "tasks": out}


@app.get("/api/tasks/{tid}")
def api_get_task(tid: str):
    t = TASKS.get(tid)
    if not t:
        raise HTTPException(404, "task not found")
    now_ts = time.time()
    out = dict(t)
    out["elapsed_seconds"] = int(now_ts - t.get("started_at_unix", now_ts))
    if t.get("status") == "active":
        since_hb = int(now_ts - t.get("last_heartbeat_unix", now_ts))
        out["seconds_since_heartbeat"] = since_hb
        out["seconds_until_ttl"] = max(0, int(t.get("ttl_seconds", 0)) - since_hb)
    return out


@app.post("/api/tasks/{tid}/heartbeat")
def api_heartbeat(tid: str, body: HeartbeatBody):
    t = TASKS.get(tid)
    if not t:
        raise HTTPException(404, "task not found")
    if t.get("status") != "active":
        raise HTTPException(400, f"task is {t.get('status')}, not active")
    now = _now()
    t["last_heartbeat"] = _iso(now)
    t["last_heartbeat_unix"] = int(now.timestamp())
    if body.extend_ttl_seconds:
        t["ttl_seconds"] = int(t.get("ttl_seconds", 0) or 0) + int(body.extend_ttl_seconds)
    if body.progress_note:
        t.setdefault("progress_notes", []).append({
            "at": _iso(now), "note": body.progress_note
        })
    _save_json(TASKS_FILE, TASKS)
    return {
        "id": tid,
        "last_heartbeat": t["last_heartbeat"],
        "ttl_seconds": t["ttl_seconds"],
        "progress_note_count": len(t.get("progress_notes", [])),
    }


@app.post("/api/tasks/{tid}/complete")
def api_complete_task(tid: str, body: CompleteTaskBody):
    t = TASKS.get(tid)
    if not t:
        raise HTTPException(404, "task not found")
    now = _now()
    t["status"] = "completed"
    t["completed_at"] = _iso(now)
    t["completed_at_unix"] = int(now.timestamp())
    t["result"] = body.result
    t["completion_note"] = body.note
    t["total_elapsed_seconds"] = int(
        now.timestamp() - t.get("started_at_unix", now.timestamp())
    )
    _save_json(TASKS_FILE, TASKS)
    _append_history({
        "event": "task_completed",
        "task_id": tid,
        "name": t.get("name"),
        "at": _iso(now),
        "elapsed_seconds": t["total_elapsed_seconds"],
    })
    return t


@app.delete("/api/tasks/{tid}")
def api_delete_task(tid: str):
    if tid not in TASKS:
        raise HTTPException(404, "task not found")
    name = TASKS[tid].get("name")
    del TASKS[tid]
    _save_json(TASKS_FILE, TASKS)
    _append_history({"event": "task_deleted", "task_id": tid, "name": name, "at": _iso(_now())})
    return {"deleted": True, "id": tid}


@app.post("/api/wakeups")
def api_schedule_wakeup(body: ScheduleWakeupBody):
    wid = uuid.uuid4().hex[:8]
    now = _now()
    fire_at_unix = int(now.timestamp()) + int(body.in_seconds)
    w = {
        "id": wid,
        "created_at": _iso(now),
        "fire_at_unix": fire_at_unix,
        "fire_at": _iso(datetime.fromtimestamp(fire_at_unix, tz=_tz())),
        "in_seconds": int(body.in_seconds),
        "message": body.message,
        "task_id": body.task_id,
        "fired": False,
    }
    WAKEUPS[wid] = w
    _save_json(WAKEUPS_FILE, WAKEUPS)
    _append_history({
        "event": "wakeup_scheduled",
        "wakeup_id": wid,
        "in_seconds": int(body.in_seconds),
        "message": body.message,
        "at": _iso(now),
    })
    return w


@app.get("/api/wakeups")
def api_list_wakeups(include_fired: bool = False):
    now_ts = int(time.time())
    items = list(WAKEUPS.values())
    if not include_fired:
        items = [w for w in items if not w.get("fired")]
    out = []
    for w in items:
        e = dict(w)
        e["seconds_until_fire"] = max(0, int(w.get("fire_at_unix", now_ts)) - now_ts)
        out.append(e)
    return {"count": len(out), "wakeups": out}


@app.delete("/api/wakeups/{wid}")
def api_cancel_wakeup(wid: str):
    if wid not in WAKEUPS:
        raise HTTPException(404, "wakeup not found")
    del WAKEUPS[wid]
    _save_json(WAKEUPS_FILE, WAKEUPS)
    _append_history({"event": "wakeup_cancelled", "wakeup_id": wid, "at": _iso(_now())})
    return {"deleted": True, "id": wid}


@app.get("/api/config")
def api_get_config():
    return CONFIG


@app.put("/api/config")
def api_put_config(body: dict):
    for k in body:
        if k not in DEFAULT_CONFIG:
            raise HTTPException(400, f"unknown config key: {k}")
    CONFIG.update(body)
    _save_config()
    _append_history({"event": "config_updated", "at": _iso(_now()), "keys": list(body.keys())})
    return CONFIG


@app.get("/api/history")
def api_history(limit: int = 100):
    if not HISTORY_FILE.exists():
        return {"events": []}
    try:
        h = json.loads(HISTORY_FILE.read_text())
    except Exception:
        h = []
    return {"events": h[-limit:]}


# ─── UI MOUNT (must be after API routes) ──────────────────
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
else:
    @app.get("/")
    def _no_ui():
        return {"warning": f"UI dir not found at {UI_DIR}", "api": "/api/status"}


# ─── ENTRYPOINT ───────────────────────────────────────────
if __name__ == "__main__":
    _ensure_dirs()
    uvicorn.run(
        app,
        host=CONFIG.get("host", "127.0.0.1"),
        port=int(CONFIG.get("port", 7779)),
        log_level="info",
    )
