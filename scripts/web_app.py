#!/usr/bin/env python3
"""
Local Web UI for simpleEA.

Goals:
- No external API calls (offline/local only)
- Read workflow state files from runs/workflow_*.json
- Link to generated offline HTML outputs under runs/
- Optionally trigger implemented post-step modules via subprocess
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import psutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import (
    DEFAULT_SYMBOL,
    DEFAULT_TIMEFRAME,
    MT5_DATA_PATH,
    MT5_EXPERTS_PATH,
    MT5_TERMINAL,
    PROJECT_ROOT,
    RUNS_DIR,
)  # type: ignore
from workflow.post_step_modules import POST_STEP_MODULES


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def _read_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _safe_relative_to_root(path: Path) -> Optional[str]:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except Exception:
        return None


def _maybe_rel(path_str: Optional[str]) -> Optional[str]:
    if not path_str:
        return None
    try:
        p = Path(path_str)
    except Exception:
        return None

    if not p.is_absolute():
        p = (PROJECT_ROOT / p).resolve()
    rel = _safe_relative_to_root(p)
    return rel


def _resolve_state_path(raw: str) -> Optional[Path]:
    if not raw:
        return None
    try:
        p = Path(raw)
    except Exception:
        return None

    if p.is_absolute():
        try:
            p = p.resolve()
            p.relative_to(PROJECT_ROOT.resolve())
        except Exception:
            return None
    else:
        p = (PROJECT_ROOT / p).resolve()
        try:
            p.relative_to(PROJECT_ROOT.resolve())
        except Exception:
            return None

    # Only allow workflow state files under runs/
    try:
        p.relative_to(RUNS_DIR.resolve())
    except Exception:
        return None

    if not p.exists() or not p.is_file():
        return None
    if p.suffix.lower() != ".json":
        return None
    if not p.name.startswith("workflow_"):
        return None
    return p


def _summarize_state(state: Dict[str, Any], state_path: Path) -> Dict[str, Any]:
    steps = state.get("steps", {}) or {}
    passed = 0
    failed = 0
    pending = 0
    for _, s in steps.items():
        if not isinstance(s, dict):
            continue
        st = (s.get("status") or "").lower()
        if st == "passed":
            passed += 1
        elif st == "failed":
            failed += 1
        else:
            pending += 1

    step11 = steps.get("11_report", {}) if isinstance(steps, dict) else {}
    out11 = step11.get("output", {}) if isinstance(step11, dict) else {}
    overall = out11.get("overall_result")

    return {
        "path": _safe_relative_to_root(state_path) or str(state_path),
        "filename": state_path.name,
        "ea_name": state.get("ea_name"),
        "symbol": state.get("symbol"),
        "timeframe": state.get("timeframe"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "current_step": state.get("current_step"),
        "steps_total": len(steps) if isinstance(steps, dict) else 0,
        "steps_passed": passed,
        "steps_failed": failed,
        "steps_pending": pending,
        "overall_result": overall,
        "dashboard_rel": _maybe_rel(out11.get("dashboard_index")) if isinstance(out11, dict) else None,
        "report_rel": _maybe_rel(out11.get("report_file")) if isinstance(out11, dict) else None,
        "backtest_report_rel": _maybe_rel(out11.get("backtest_report")) if isinstance(out11, dict) else None,
        "history_quality": out11.get("history_quality") if isinstance(out11, dict) else None,
        "bars": out11.get("bars") if isinstance(out11, dict) else None,
        "ticks": out11.get("ticks") if isinstance(out11, dict) else None,
    }


def _list_states(limit: int = 100) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    paths = sorted(RUNS_DIR.glob("workflow_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in paths[: max(0, int(limit))]:
        try:
            state = _read_json(p)
            items.append(_summarize_state(state, p))
        except Exception as e:
            items.append({"path": _safe_relative_to_root(p) or str(p), "filename": p.name, "error": str(e)})
    return items


def _tail_text(path: Path, max_bytes: int = 8000) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max_bytes), os.SEEK_SET)
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _terminal_bases() -> List[Path]:
    bases: List[Path] = []
    appdata = os.environ.get("APPDATA")
    localappdata = os.environ.get("LOCALAPPDATA")
    if appdata:
        bases.append(Path(appdata) / "MetaQuotes" / "Terminal")
    if localappdata:
        bases.append(Path(localappdata) / "MetaQuotes" / "Terminal")
    return [b for b in bases if b.exists()]


def _read_origin_path(data_dir: Path) -> Optional[Path]:
    origin = data_dir / "origin.txt"
    if not origin.exists():
        return None
    try:
        b = origin.read_bytes()
        # Some terminals write origin.txt as UTF-16 (null bytes between chars).
        if b"\x00" in b[:64]:
            raw = b.decode("utf-16", errors="ignore").strip()
        else:
            raw = b.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    if not raw:
        return None
    return Path(raw)


def _latest_mtime_under(path: Path, glob: str) -> Optional[float]:
    if not path.exists():
        return None
    latest: Optional[float] = None
    try:
        for p in path.glob(glob):
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            if latest is None or mt > latest:
                latest = mt
    except Exception:
        return None
    return latest


def _running_mt5_processes() -> Dict[Path, List[int]]:
    """
    Map MT5 install dirs -> list of PIDs.

    We use the process executable directory as the install dir (origin.txt matches this).
    """
    by_install: Dict[Path, List[int]] = {}
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            name = (proc.info.get("name") or "").lower()
            exe = proc.info.get("exe")
            if not exe:
                continue
            exe_path = Path(exe)
            if not exe_path.exists():
                continue
            if "terminal64" not in name and exe_path.name.lower() not in ("terminal64.exe", "terminal.exe"):
                continue
            install_dir = exe_path.parent.resolve()
            by_install.setdefault(install_dir, []).append(int(proc.info["pid"]))
        except Exception:
            continue
    return by_install


def _discover_terminals() -> List[Dict[str, Any]]:
    """
    Discover terminal data folders (and try to mark which ones are currently open).

    Returns entries with:
      - id: terminal data folder name (hash)
      - data_path: absolute path to terminal data folder
      - experts_path: absolute path to MQL5/Experts
      - origin_path: origin.txt install dir (best-effort)
      - terminal_exe: guessed terminal64.exe path (best-effort)
      - is_running: whether a matching terminal64.exe process is running (best-effort)
      - pids: list of PIDs if running
    """
    running = _running_mt5_processes()
    out: List[Dict[str, Any]] = []

    seen: set[str] = set()
    for base in _terminal_bases():
        for data_dir in base.iterdir():
            if not data_dir.is_dir():
                continue
            if data_dir.name.lower() in {"common", "community", "help"}:
                continue
            if data_dir.name in seen:
                continue
            seen.add(data_dir.name)

            experts = data_dir / "MQL5" / "Experts"
            if not experts.exists():
                continue

            origin = _read_origin_path(data_dir)
            install_dir = origin.resolve() if origin else None

            pids: List[int] = []
            if install_dir and install_dir in running:
                pids = running[install_dir]

            latest_log = _latest_mtime_under(data_dir / "logs", "*.log")
            if latest_log is None:
                latest_log = _latest_mtime_under(data_dir / "Tester" / "logs", "*.log")

            terminal_exe = None
            if origin:
                cand = origin / "terminal64.exe"
                if cand.exists():
                    terminal_exe = str(cand)
                else:
                    cand2 = origin / "terminal.exe"
                    terminal_exe = str(cand2) if cand2.exists() else str(cand)

            out.append(
                {
                    "id": data_dir.name,
                    "data_path": str(data_dir),
                    "experts_path": str(experts),
                    "origin_path": str(origin) if origin else None,
                    "terminal_exe": terminal_exe,
                    "is_running": bool(pids),
                    "pids": pids,
                    "latest_log_mtime": latest_log,
                    "is_default": data_dir.resolve() == MT5_DATA_PATH.resolve(),
                }
            )

    out.sort(key=lambda d: (not bool(d.get("is_running")), not bool(d.get("is_default")), str(d.get("id"))))
    return out


def _resolve_terminal_by_id(terminal_id: str) -> Optional[Dict[str, Any]]:
    tid = (terminal_id or "").strip()
    if not tid:
        return None
    for t in _discover_terminals():
        if t.get("id") == tid:
            return t
    return None


def _list_eas_in_experts(experts_path: Path, *, max_files: int = 2000) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not experts_path.exists():
        return out

    count = 0
    for p in experts_path.rglob("*.mq5"):
        if not p.is_file():
            continue
        try:
            rel = p.relative_to(experts_path).as_posix()
        except Exception:
            rel = p.name

        try:
            st = p.stat()
            size = int(st.st_size)
            mtime = float(st.st_mtime)
        except OSError:
            size = 0
            mtime = 0.0

        out.append(
            {
                "name": p.stem,
                "rel_path": rel,
                "abs_path": str(p),
                "size_bytes": size,
                "mtime": mtime,
            }
        )
        count += 1
        if count >= max_files:
            break

    out.sort(key=lambda d: (str(d.get("name") or "").lower(), str(d.get("rel_path") or "")))
    return out


@dataclass
class Job:
    id: str
    module_id: str
    state_path: str
    command: List[str]
    started_at: float
    ended_at: Optional[float] = None
    returncode: Optional[int] = None
    status: str = "running"  # running|completed|failed
    log_rel: Optional[str] = None


_JOBS_LOCK = threading.Lock()
_JOBS: Dict[str, Dict[str, Any]] = {}


def _jobs_dir() -> Path:
    d = RUNS_DIR / "web_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _spawn_job(module_id: str, state_path: Path, extra_args: Optional[List[str]] = None) -> Job:
    job_id = time.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}_{int(time.time() * 1000) % 1000:03d}"

    scripts: Dict[str, List[str]] = {
        "execution_stress": ["scripts/run_execution_stress.py"],
        "walk_forward": ["scripts/run_walk_forward.py"],
        "multipair": ["scripts/run_multipair.py"],
        "timeframes": ["scripts/run_timeframes.py"],
    }
    if module_id not in scripts:
        raise ValueError(f"Unknown/unsupported module_id: {module_id}")

    cmd = [sys.executable, *scripts[module_id], "--state", str(state_path)]
    if extra_args:
        cmd.extend([str(a) for a in extra_args if str(a).strip()])

    log_path = _jobs_dir() / f"{job_id}_{module_id}.log"
    log_f = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        text=True,
    )

    job = Job(
        id=job_id,
        module_id=module_id,
        state_path=_safe_relative_to_root(state_path) or str(state_path),
        command=[str(c) for c in cmd],
        started_at=time.time(),
        status="running",
        log_rel=_safe_relative_to_root(log_path) or str(log_path),
    )

    with _JOBS_LOCK:
        _JOBS[job_id] = {"job": job, "proc": proc, "log_f": log_f, "log_path": log_path}

    return job


def _spawn_workflow_job(config: Dict[str, Any]) -> Job:
    job_id = time.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}_{int(time.time() * 1000) % 1000:03d}"

    cfg_path = _jobs_dir() / f"{job_id}_workflow.json"
    cfg_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    cmd = [sys.executable, "scripts/run_workflow.py", "--config", str(cfg_path)]

    log_path = _jobs_dir() / f"{job_id}_workflow.log"
    log_f = open(log_path, "w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        stdout=log_f,
        stderr=subprocess.STDOUT,
        text=True,
    )

    job = Job(
        id=job_id,
        module_id="workflow",
        state_path="",
        command=[str(c) for c in cmd],
        started_at=time.time(),
        status="running",
        log_rel=_safe_relative_to_root(log_path) or str(log_path),
    )

    with _JOBS_LOCK:
        _JOBS[job_id] = {"job": job, "proc": proc, "log_f": log_f, "log_path": log_path, "cfg_path": cfg_path}

    return job


def _poll_jobs() -> List[Job]:
    out: List[Job] = []
    with _JOBS_LOCK:
        for job_id, entry in list(_JOBS.items()):
            job: Job = entry["job"]
            proc: subprocess.Popen[str] = entry["proc"]
            if job.status == "running":
                rc = proc.poll()
                if rc is not None:
                    job.returncode = int(rc)
                    job.ended_at = time.time()
                    job.status = "completed" if rc == 0 else "failed"
                    try:
                        entry["log_f"].close()
                    except Exception:
                        pass
            out.append(job)
    out.sort(key=lambda j: j.started_at, reverse=True)
    return out


class _Handler(SimpleHTTPRequestHandler):
    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: int = 200, content_type: str = "text/plain; charset=utf-8") -> None:
        body = (text or "").encode("utf-8", errors="replace")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path in ("/", "/index.html"):
            self.path = "/webapp/index.html"
            return super().do_GET()

        if parsed.path == "/api/health":
            return self._send_json({"ok": True, "now": _now_iso()})

        if parsed.path == "/api/states":
            qs = parse_qs(parsed.query or "")
            limit = int((qs.get("limit") or ["100"])[0])
            return self._send_json({"states": _list_states(limit=limit)})

        if parsed.path == "/api/state":
            qs = parse_qs(parsed.query or "")
            raw = (qs.get("path") or [""])[0]
            state_path = _resolve_state_path(raw)
            if not state_path:
                return self._send_json({"error": "Invalid state path"}, status=400)
            try:
                state = _read_json(state_path)
            except Exception as e:
                return self._send_json({"error": str(e)}, status=500)
            return self._send_json({"state": state, "summary": _summarize_state(state, state_path)})

        if parsed.path == "/api/modules":
            mods = [
                {
                    "id": m.id,
                    "title": m.title,
                    "description": m.description,
                    "implemented": bool(m.implemented),
                    "command_template": m.command_template,
                    "state_key": m.state_key,
                }
                for m in POST_STEP_MODULES
            ]
            return self._send_json({"modules": mods})

        if parsed.path == "/api/terminals":
            return self._send_json(
                {
                    "terminals": _discover_terminals(),
                    "default": {
                        "terminal_exe": str(MT5_TERMINAL),
                        "data_path": str(MT5_DATA_PATH),
                        "experts_path": str(MT5_EXPERTS_PATH),
                    },
                }
            )

        if parsed.path == "/api/eas":
            qs = parse_qs(parsed.query or "")
            terminal_id = str((qs.get("terminal_id") or [""])[0]).strip()
            t = _resolve_terminal_by_id(terminal_id)
            if not t:
                return self._send_json({"error": "Unknown terminal_id"}, status=400)
            experts = Path(str(t["experts_path"]))
            return self._send_json(
                {"terminal_id": terminal_id, "experts_path": str(experts), "eas": _list_eas_in_experts(experts)}
            )

        if parsed.path == "/api/jobs":
            jobs = _poll_jobs()
            payload = []
            for j in jobs:
                log_text = None
                if j.log_rel:
                    log_path = (PROJECT_ROOT / j.log_rel).resolve()
                    log_text = _tail_text(log_path) if log_path.exists() else ""
                payload.append(
                    {
                        "id": j.id,
                        "module_id": j.module_id,
                        "state_path": j.state_path,
                        "command": j.command,
                        "started_at": j.started_at,
                        "ended_at": j.ended_at,
                        "returncode": j.returncode,
                        "status": j.status,
                        "log_rel": j.log_rel,
                        "log_tail": log_text,
                    }
                )
            return self._send_json({"jobs": payload, "now": _now_iso()})

        return super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/run", "/api/workflow/run"):
            return self._send_json({"error": "Not found"}, status=404)

        try:
            length = int(self.headers.get("Content-Length") or "0")
        except Exception:
            length = 0
        raw = self.rfile.read(max(0, length))
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return self._send_json({"error": "Invalid JSON"}, status=400)

        if parsed.path == "/api/workflow/run":
            terminal_id = str(payload.get("terminal_id") or "").strip()
            ea_rel = str(payload.get("ea_rel_path") or "").strip().replace("\\", "/")
            symbol = str(payload.get("symbol") or DEFAULT_SYMBOL).strip()
            timeframe = str(payload.get("timeframe") or DEFAULT_TIMEFRAME).strip()
            options = payload.get("options") or {}

            if not terminal_id or not ea_rel:
                return self._send_json({"error": "terminal_id and ea_rel_path are required"}, status=400)
            if not isinstance(options, dict):
                return self._send_json({"error": "options must be an object"}, status=400)

            t = _resolve_terminal_by_id(terminal_id)
            if not t:
                return self._send_json({"error": "Unknown terminal_id"}, status=400)
            experts = Path(str(t["experts_path"]))
            ea_path = (experts / ea_rel).resolve()
            if not ea_path.exists() or ea_path.suffix.lower() != ".mq5":
                return self._send_json({"error": f"EA not found: {ea_rel}"}, status=400)
            try:
                ea_path.relative_to(experts.resolve())
            except Exception:
                return self._send_json({"error": "Invalid ea_rel_path (outside Experts)"}, status=400)

            cfg = {
                "ea_path": str(ea_path),
                "symbol": symbol,
                "timeframe": timeframe,
                "options": options,
                "source": {"terminal_id": terminal_id, "experts_path": str(experts), "ea_rel_path": ea_rel},
            }

            try:
                job = _spawn_workflow_job(cfg)
            except Exception as e:
                return self._send_json({"error": str(e)}, status=500)

            return self._send_json({"ok": True, "job": {"id": job.id, "status": job.status}})

        module_id = str(payload.get("module_id") or "").strip()
        state_raw = str(payload.get("state_path") or "").strip()
        extra_args = payload.get("extra_args")

        mod = next((m for m in POST_STEP_MODULES if m.id == module_id), None)
        if not mod or not mod.implemented:
            return self._send_json({"error": "Unknown or unimplemented module_id"}, status=400)

        state_path = _resolve_state_path(state_raw)
        if not state_path:
            return self._send_json({"error": "Invalid state_path"}, status=400)

        if extra_args is not None and not isinstance(extra_args, list):
            return self._send_json({"error": "extra_args must be a list"}, status=400)

        try:
            job = _spawn_job(module_id=module_id, state_path=state_path, extra_args=extra_args)
        except Exception as e:
            return self._send_json({"error": str(e)}, status=500)

        return self._send_json({"ok": True, "job": {"id": job.id, "status": job.status}})


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Local web UI for simpleEA (offline)")
    ap.add_argument("--host", type=str, default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    ap.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    ap.add_argument("--open", action="store_true", help="Open the web UI in your browser")
    return ap.parse_args()


def main() -> None:
    args = _parse_args()

    url = f"http://{args.host}:{int(args.port)}/"
    handler = lambda *a, **kw: _Handler(*a, directory=str(PROJECT_ROOT), **kw)  # type: ignore[arg-type]
    httpd = ThreadingHTTPServer((args.host, int(args.port)), handler)

    print(f"simpleEA web app running at: {url}")
    print(f"Serving files from: {PROJECT_ROOT}")
    print(f"Workflow states: {RUNS_DIR}")
    print(f"MT5 data path (read-only here): {MT5_DATA_PATH}")

    if args.open:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
