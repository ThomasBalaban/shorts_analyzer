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
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from analyzer import YouTubeShortAnalyzer  # noqa: E402
from analyzer import rerun as rerun_mod  # noqa: E402

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
    "last_result": None,     # dict, populated by rerun jobs on success
    "progress": {
        "phase": "idle",     # "idle" | "fetching" | "analyzing" | "done" | "error"
        "current": 0,
        "total": 0,
        "current_title": "",
    },
}
_lock = threading.Lock()


# Reruns use the same single-slot worker pattern as /analyze/start so only
# one long-running job exists at a time. Callers poll /analyze/status to
# watch progress, then read /videos or the written file for results.
def _output_path(name: str) -> str:
    if not name or "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "Invalid filename")
    if not name.endswith(".json"):
        name = name + ".json"
    full = os.path.join(OUTPUT_DIR, name)
    if not os.path.isfile(full):
        raise HTTPException(404, f"File not found: {name}")
    return full


def _start_worker(kind: str, desc: dict, run) -> None:
    """Acquire the single worker slot and launch `run()`.

    `kind` labels the job ("analyze" | "rerun_analysis" | ...).
    `desc` is a small dict summarizing what was requested, merged into
    `current_job` for status polling. `run` is a zero-arg callable —
    endpoints build it via closure so parameters are captured cleanly.
    Raises HTTPException(409) if another job is already running.
    """
    if _state["running"]:
        raise HTTPException(409, "A job is already running")
    with _lock:
        _state["running"] = True
        _state["stop_requested"] = False
        _state["last_error"] = None
        _state["last_result"] = None
        _state["current_job"] = {
            "kind": kind,
            "started_at": time.time(),
            **desc,
        }
        _state["progress"] = {
            "phase": kind,
            "current": 0,
            "total": 0,
            "current_title": "",
        }

    def _body():
        _log(f"=== {kind} started ===")
        try:
            result = run()
            with _lock:
                _state["last_result"] = result
                _state["progress"]["phase"] = "done"
            _log(f"✅ {kind} finished cleanly")
        except InterruptedError:
            _log(f"⏹  {kind} stopped by user")
            with _lock:
                _state["progress"]["phase"] = "idle"
        except Exception as e:
            import traceback
            err = str(e)
            _log(f"❌ {kind} failed: {err}")
            _log(traceback.format_exc())
            with _lock:
                _state["last_error"] = err
                _state["progress"]["phase"] = "error"
        finally:
            with _lock:
                _state["running"] = False
                _state["stop_requested"] = False
            _log(f"=== {kind} worker exited ===")

    threading.Thread(target=_body, daemon=True).start()


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


class RerunRequest(BaseModel):
    """Body for POST /rerun/*. Exactly one of `video_ids` or `filter` must
    be set. `output` is the analyzer JSON filename in output/."""
    output: str
    video_ids: Optional[List[str]] = None
    filter: Optional[str] = None


class RerunTailwindRequest(RerunRequest):
    include_all: bool = False
    use_trends: bool = False


class RerunSynthesisRequest(BaseModel):
    output: str
    skip_narrative: bool = False


def _validate_rerun_body(req: RerunRequest, phase: str) -> None:
    """Refuse ambiguous or missing selectors at the API boundary.

    For the expensive Phase 2 rerun we additionally refuse
    `filter=all` — the operator has to either name video_ids or pick a
    narrower predicate. Prevents "rerun everything" being one typo away.
    """
    if req.video_ids is None and req.filter is None:
        raise HTTPException(
            400, "Provide either `video_ids` or `filter`.")
    if req.video_ids is not None and req.filter is not None:
        raise HTTPException(
            400, "Specify `video_ids` OR `filter`, not both.")
    if req.filter is not None and req.filter not in rerun_mod.FILTERS:
        raise HTTPException(
            400,
            f"Unknown filter '{req.filter}'. "
            f"Allowed: {sorted(rerun_mod.FILTERS)}")
    if phase == "analysis" and req.filter == "all":
        raise HTTPException(
            400,
            "filter='all' is refused for /rerun/analysis to prevent "
            "accidental full-corpus reruns. Pass explicit video_ids "
            "or pick a narrower predicate (e.g. model_mismatch).")


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


# ─── Rerun ────────────────────────────────────────────────────────────────────

@app.get("/videos")
def list_videos(output: str):
    """List every video in the corpus with its per-phase `_meta` state.

    Response includes `stale_reasons` per phase — the predicate labels
    that would select that video for rerun. No action is taken by this
    endpoint; the operator reads it and decides.
    """
    full = _output_path(output)
    try:
        return rerun_mod.list_videos(full)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/rerun/analytics")
def rerun_analytics(req: RerunRequest):
    _validate_rerun_body(req, phase="analytics")
    full = _output_path(req.output)
    desc = {"output": req.output, "video_ids": req.video_ids,
            "filter": req.filter}
    _start_worker(
        "rerun_analytics", desc,
        lambda: rerun_mod.rerun_analytics(
            full,
            video_ids=req.video_ids,
            filter=req.filter,
            log_func=_log_and_track,
            stop_flag=lambda: _state["stop_requested"],
        ),
    )
    return {"ok": True, "kind": "rerun_analytics", **desc}


@app.post("/rerun/analysis")
def rerun_analysis(req: RerunRequest):
    _validate_rerun_body(req, phase="analysis")
    full = _output_path(req.output)
    desc = {"output": req.output, "video_ids": req.video_ids,
            "filter": req.filter}
    _start_worker(
        "rerun_analysis", desc,
        lambda: rerun_mod.rerun_analysis(
            full,
            video_ids=req.video_ids,
            filter=req.filter,
            log_func=_log_and_track,
            stop_flag=lambda: _state["stop_requested"],
        ),
    )
    return {"ok": True, "kind": "rerun_analysis", **desc}


@app.post("/rerun/synthesis")
def rerun_synthesis(req: RerunSynthesisRequest):
    full = _output_path(req.output)
    desc = {"output": req.output, "skip_narrative": req.skip_narrative}
    _start_worker(
        "rerun_synthesis", desc,
        lambda: rerun_mod.rerun_synthesis(
            full,
            skip_narrative=req.skip_narrative,
            log_func=_log_and_track,
        ),
    )
    return {"ok": True, "kind": "rerun_synthesis", **desc}


@app.post("/rerun/tailwind")
def rerun_tailwind(req: RerunTailwindRequest):
    if req.video_ids is not None and req.filter is not None:
        raise HTTPException(
            400, "Specify `video_ids` OR `filter`, not both.")
    if req.filter is not None and req.filter not in rerun_mod.FILTERS:
        raise HTTPException(
            400,
            f"Unknown filter '{req.filter}'. "
            f"Allowed: {sorted(rerun_mod.FILTERS)}")
    full = _output_path(req.output)
    desc = {
        "output": req.output,
        "video_ids": req.video_ids,
        "filter": req.filter,
        "include_all": req.include_all,
        "use_trends": req.use_trends,
    }
    _start_worker(
        "rerun_tailwind", desc,
        lambda: rerun_mod.rerun_tailwind(
            full,
            video_ids=req.video_ids,
            filter=req.filter,
            include_all=req.include_all,
            use_trends=req.use_trends,
            log_func=_log_and_track,
        ),
    )
    return {"ok": True, "kind": "rerun_tailwind", **desc}


# ─── Control ──────────────────────────────────────────────────────────────────

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
        "last_result": _state["last_result"],
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
