"""
Post-step module tracking for workflow state files.

These post-step modules are OPTIONAL add-ons that run after the core workflow
(Step 11). We record their runs into the workflow state JSON so future agents
and tools can see what was executed and where outputs were written.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _now_iso() -> str:
    return datetime.now().isoformat()


def _new_run_id() -> str:
    # Use a sortable timestamp + milliseconds.
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


@dataclass
class PostStepRun:
    """A single execution of an optional post-step module."""

    id: str
    name: str
    status: str  # in_progress | passed | failed
    started_at: str
    completed_at: Optional[str] = None
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_state(state_path: Path) -> Dict[str, Any]:
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state_path: Path, data: Dict[str, Any]) -> None:
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def start_post_step(state_path: Optional[Path], name: str, *, meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """
    Append an in-progress post-step run to the state file and return its run id.

    If state_path is None, this is a no-op and returns None.
    """
    if not state_path:
        return None

    run_id = _new_run_id()
    data = load_state(state_path)
    run = PostStepRun(
        id=run_id,
        name=name,
        status="in_progress",
        started_at=_now_iso(),
        output=meta or {},
    )
    data.setdefault("post_steps", [])
    data["post_steps"].append(run.to_dict())
    data["updated_at"] = _now_iso()
    save_state(state_path, data)
    return run_id


def _find_run(data: Dict[str, Any], run_id: str) -> Tuple[Optional[Dict[str, Any]], Optional[int]]:
    runs = data.get("post_steps", []) or []
    for idx, r in enumerate(runs):
        if isinstance(r, dict) and r.get("id") == run_id:
            return r, idx
    return None, None


def complete_post_step(state_path: Optional[Path], run_id: Optional[str], *, output: Optional[Dict[str, Any]] = None) -> None:
    """Mark a post-step run as passed."""
    if not state_path or not run_id:
        return

    data = load_state(state_path)
    run, idx = _find_run(data, run_id)
    if run is None or idx is None:
        return

    run = dict(run)
    run["status"] = "passed"
    run["completed_at"] = _now_iso()
    if output:
        merged = dict(run.get("output") or {})
        merged.update(output)
        run["output"] = merged
    run["error"] = None

    data["post_steps"][idx] = run
    data["updated_at"] = _now_iso()
    save_state(state_path, data)


def fail_post_step(
    state_path: Optional[Path],
    run_id: Optional[str],
    *,
    error: str,
    output: Optional[Dict[str, Any]] = None,
) -> None:
    """Mark a post-step run as failed."""
    if not state_path or not run_id:
        return

    data = load_state(state_path)
    run, idx = _find_run(data, run_id)
    if run is None or idx is None:
        return

    run = dict(run)
    run["status"] = "failed"
    run["completed_at"] = _now_iso()
    run["error"] = error
    if output:
        merged = dict(run.get("output") or {})
        merged.update(output)
        run["output"] = merged

    data["post_steps"][idx] = run
    data["updated_at"] = _now_iso()
    save_state(state_path, data)

