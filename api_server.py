"""
Shorts Analyzer Headless API Server
REST API for driving the analyzer from another app (e.g. a hub).
Port: 9021  (SimpleAutoSubs uses 9020)
"""
import os
import sys
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from analyzer import YouTubeShortAnalyzer  # noqa: E402

PORT = 9021
OUTPUT_DIR = os.path.join(_HERE, "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Shared state ─────────────────────────────────────────────────────────────

_logs: deque = deque(maxlen=500)
_state: Dict[str, Any] = {
    "running": False,
    "stop_requested": False,
    "current_job": None,     # dict describing the active job
    "last_error": None,      # str, cleared on new job
    "progress": {
        "phase": "idle",     # "idle" | "fetching" | "analyzing" | "done" | "error"
        "current": 0,
        "total": 0,
        "current_title": "",
    },
}
_lock = threading.Lock()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    _logs.append(line)
    print(line, flush=True)


def _parse_progress_from_log(msg: str) -> None:
    """Best-effort progress tracking by sniffing analyzer log lines."""
    prog = _state["progress"]
    if msg.startswith("Fetching shorts from channel"):
        prog["phase"] = "fetching"
    elif msg.startswith("Selected top"):
        # "Selected top N shorts by view count"
        try:
            parts = msg.split()
            prog["total"] = int(parts[2])
            prog["phase"] = "analyzing"
        except Exception:
            pass
    elif msg.lstrip().startswith("["):
        # "[RANK/TOTAL] Processing: TITLE"  or  "[RANK/TOTAL] Skipping ..."
        try:
            bracket = msg[msg.index("[") + 1:msg.index("]")]
            current_str, total_str = bracket.split("/")
            prog["current"] = int(current_str)
            prog["total"] = int(total_str)
            if "Processing:" in msg:
                prog["current_title"] = msg.split("Processing:", 1)[1].strip()
        except Exception:
            pass


def _log_and_track(msg: str) -> None:
    _log(msg)
    try:
        _parse_progress_from_log(msg)
    except Exception:
        pass


def _analyzer_worker(
    channel_url: str,
    output_filename: str,
    max_shorts: int,
) -> None:
    output_path = os.path.join(OUTPUT_DIR, output_filename)
    _log(f"=== Analysis started: {channel_url} ===")
    _log(f"    Output: {output_path}")
    _log(f"    Max shorts: {max_shorts}")

    with _lock:
        _state["current_job"] = {
            "channel_url": channel_url,
            "output_filename": output_filename,
            "output_path": output_path,
            "max_shorts": max_shorts,
            "started_at": time.time(),
        }
        _state["last_error"] = None
        _state["progress"] = {
            "phase": "fetching",
            "current": 0,
            "total": 0,
            "current_title": "",
        }

    analyzer = None
    try:
        analyzer = YouTubeShortAnalyzer(
            channel_url=channel_url,
            output_file=output_path,
            max_shorts=max_shorts,
            log_func=_log_and_track,
            stop_flag=lambda: _state["stop_requested"],
        )
        analyzer.process_shorts()
        with _lock:
            _state["progress"]["phase"] = "done"
        _log("✅ Analysis finished cleanly")

    except InterruptedError:
        _log("⏹  Analysis stopped by user")
        with _lock:
            _state["progress"]["phase"] = "idle"

    except Exception as e:
        import traceback
        err = str(e)
        _log(f"❌ Analysis failed: {err}")
        _log(traceback.format_exc())
        with _lock:
            _state["last_error"] = err
            _state["progress"]["phase"] = "error"

    finally:
        if analyzer is not None:
            try:
                analyzer.cleanup()
            except Exception:
                pass
        with _lock:
            _state["running"] = False
            _state["stop_requested"] = False
        _log("=== Analysis worker exited ===")


# ─── Pydantic models ──────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    channel_url: str
    output_filename: Optional[str] = None   # defaults to "<handle>.json"
    max_shorts: int = 100


# ─── App lifecycle ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    _log(f"✅ Shorts Analyzer API ready on :{PORT}")
    _log(f"   Output directory: {OUTPUT_DIR}")
    yield
    _log("Shorts Analyzer API stopping.")


app = FastAPI(title="Shorts Analyzer API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "port": PORT, "output_dir": OUTPUT_DIR}


# ─── Control ──────────────────────────────────────────────────────────────────

@app.post("/analyze/start")
def analyze_start(req: StartRequest):
    if _state["running"]:
        raise HTTPException(409, "Analysis already running")

    if not req.channel_url.strip():
        raise HTTPException(400, "channel_url is required")

    # Derive a default output filename from the channel handle if none given
    output_filename = req.output_filename
    if not output_filename:
        handle = req.channel_url.rstrip("/").split("/")
        handle = next((p for p in handle if p.startswith("@")), "shorts")
        output_filename = f"{handle.lstrip('@')}.json"
    if not output_filename.endswith(".json"):
        output_filename += ".json"

    with _lock:
        _state["running"] = True
        _state["stop_requested"] = False

    threading.Thread(
        target=_analyzer_worker,
        args=(req.channel_url, output_filename, req.max_shorts),
        daemon=True,
    ).start()

    return {
        "ok": True,
        "channel_url": req.channel_url,
        "output_filename": output_filename,
        "max_shorts": req.max_shorts,
    }


@app.post("/analyze/stop")
def analyze_stop():
    if not _state["running"]:
        return {"ok": False, "reason": "not_running"}
    with _lock:
        _state["stop_requested"] = True
    return {
        "ok": True,
        "message": "Stop requested — will halt after current video.",
    }


@app.get("/analyze/status")
def analyze_status():
    return {
        "running": _state["running"],
        "stop_requested": _state["stop_requested"],
        "current_job": _state["current_job"],
        "last_error": _state["last_error"],
        "progress": _state["progress"],
    }


# ─── Logs ─────────────────────────────────────────────────────────────────────

@app.get("/logs")
def get_logs(last: int = 200):
    return {"lines": list(_logs)[-last:]}


@app.delete("/logs")
def clear_logs():
    _logs.clear()
    return {"ok": True}


# ─── Results (JSON files) ─────────────────────────────────────────────────────

@app.get("/results")
def list_results():
    """List all analysis JSON files in the output directory."""
    files = []
    try:
        for name in os.listdir(OUTPUT_DIR):
            if not name.endswith(".json"):
                continue
            full = os.path.join(OUTPUT_DIR, name)
            if not os.path.isfile(full):
                continue
            stat = os.stat(full)
            files.append({
                "name": name,
                "path": full,
                "modified": stat.st_mtime,
                "size": stat.st_size,
            })
        files.sort(key=lambda x: x["modified"], reverse=True)
    except Exception as e:
        raise HTTPException(500, str(e))
    return {"files": files, "dir": OUTPUT_DIR}


@app.get("/results/read")
def read_result(name: str):
    """Read a result JSON file by filename (no paths allowed)."""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid filename")
    full = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    try:
        import json as _json
        with open(full, "r", encoding="utf-8") as f:
            return _json.load(f)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/results/download")
def download_result(name: str):
    """Download a result JSON file as an attachment."""
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid filename")
    full = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    return FileResponse(
        full, media_type="application/json", filename=name)


@app.delete("/results/{name}")
def delete_result(name: str):
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid filename")
    full = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(full):
        raise HTTPException(404, "File not found")
    try:
        os.remove(full)
        return {"ok": True, "deleted": name}
    except Exception as e:
        raise HTTPException(500, str(e))


# ─── Entry ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
