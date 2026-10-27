"""Persistent progressive-audit state, written atomically and locked when AIKit is present."""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from reforge.errors import ReforgeError
from reforge.model import Finding, Repair, StagePlan

SCHEMA_VERSION = 1
STATE_REL = Path(".aikit") / "reforge.json"
MAX_HISTORY = 20


def state_path(root: Path) -> Path:
    return Path(root) / STATE_REL


def new_state() -> Dict[str, object]:
    return {
        "schema": SCHEMA_VERSION,
        "stage": 0,
        "window": 0,
        "audited_commits": [],
        "last_audit": None,
        "history": [],
    }


def load_state(root: Path) -> Dict[str, object]:
    """Read the state; a missing file is a fresh audit, an unreadable one is refused."""
    path = state_path(root)
    if not path.is_file():
        return new_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ReforgeError(
            f"Cannot read {path}.",
            f"the file holds Reforge's audit progress and is not valid JSON: {exc}",
            f"restore {path.name}.bak or remove the file to start a fresh audit; no code was changed.",
        ) from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA_VERSION:
        raise ReforgeError(
            f"{path} has an unsupported Reforge schema.",
            f"this Reforge reads schema {SCHEMA_VERSION} only.",
            "update Reforge, or restore the file from the project's git history.",
        )
    for key, default in (("stage", 0), ("window", 0), ("audited_commits", []),
                         ("last_audit", None), ("history", [])):
        data.setdefault(key, default)
    if not isinstance(data["audited_commits"], list) or not isinstance(data["history"], list):
        raise ReforgeError(
            f"{path} is structurally invalid.",
            "'audited_commits' and 'history' must be lists.",
            "restore the file from its .bak shadow or a committed copy.",
        )
    return data


def _local_atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp_{os.getpid()}_{int(time.time() * 1000)}")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:  # hygiene: allow temp cleanup cannot fail the completed write
                pass


def save_state(root: Path, data: Dict[str, object]) -> None:
    """Persist through AIKit's atomic writer and lock when available, else a portable fallback."""
    path = state_path(root)
    text = json.dumps(data, indent=2)
    try:
        from scripts.disruption_recovery import atomic_write_json, file_lock
    except ImportError:
        _local_atomic_write(path, text)
        return
    with file_lock(path) as acquired:
        if not acquired:
            raise ReforgeError(
                f"Could not lock {path}.",
                "another Reforge process is writing the same audit state.",
                "retry in a moment; if no process is running, remove the stale .lock file.",
            )
        atomic_write_json(path, data)


def entry_from_stage(plan: StagePlan, findings: List[Finding], repairs: List[Repair],
                     tests: Optional[Dict[str, object]] = None,
                     gates: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    counts: Dict[str, int] = {}
    for finding in findings:
        counts[finding.category] = counts.get(finding.category, 0) + 1
    return {
        "stage": plan.stage,
        "window": plan.window,
        "commits": [commit.sha for commit in plan.commits],
        "new_commits": list(plan.new_shas),
        "prior_commits": list(plan.prior_shas),
        "findings": [finding.as_dict() for finding in findings],
        "repairs": [repair.as_dict() for repair in repairs],
        "counts": counts,
        "tests": tests or {},
        "gates": gates or {},
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def record_stage(root: Path, state: Dict[str, object], entry: Dict[str, object]) -> Dict[str, object]:
    """Advance the stage, remember every audited SHA, and keep bounded history."""
    state["stage"] = entry["stage"]
    state["window"] = entry["window"]
    audited = list(state.get("audited_commits") or [])
    known = set(audited)
    audited.extend(sha for sha in entry["new_commits"] if sha not in known)
    state["audited_commits"] = audited
    state["last_audit"] = entry
    history = list(state.get("history") or [])
    history.append(entry)
    state["history"] = history[-MAX_HISTORY:]
    save_state(root, state)
    return state


def mark_repairs(root: Path, state: Dict[str, object], repairs: List[Repair]) -> Dict[str, object]:
    """Mark the repaired findings in the last audit entry so `fix` is idempotent."""
    keys = {(repair.code, repair.path, repair.line) for repair in repairs if repair.applied}
    last = state.get("last_audit")
    if isinstance(last, dict):
        for item in last.get("findings") or []:
            if (item.get("code"), item.get("path"), item.get("line")) in keys:
                item["repaired"] = True
    save_state(root, state)
    return state


def unrepaired_findings(state: Dict[str, object]) -> List[Dict[str, object]]:
    last = state.get("last_audit")
    if not isinstance(last, dict):
        return []
    return [item for item in last.get("findings") or [] if not item.get("repaired")]


def last_stage(state: Dict[str, object]) -> int:
    return int(state.get("stage") or 0)
