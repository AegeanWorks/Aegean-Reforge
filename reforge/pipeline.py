"""Orchestrates one progressive audit, its safe repairs and their verification."""

import dataclasses
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from reforge.audit import audit_window, plan_next_stage, summarize, window_for_stage
from reforge.errors import ReforgeError
from reforge.git_history import dirty_paths, head_sha
from reforge.model import Finding, Repair, StagePlan
from reforge.repair import regression_test_path, repair_findings, repair_paths
from reforge.state import (
    STATE_REL,
    entry_from_stage,
    last_stage,
    load_state,
    mark_repairs,
    record_stage,
    save_state,
    unrepaired_findings,
)
from reforge.verification import (
    default_test_command,
    recheck_repairs,
    review_patch,
    run_test_command,
)

GateRunner = Callable[[], Tuple[bool, Sequence[str]]]


def finding_from_dict(item: Dict[str, object]) -> Finding:
    fields = {field.name for field in dataclasses.fields(Finding)}
    return Finding(**{key: value for key, value in item.items() if key in fields})


def _scanner(label: str, text: str):
    try:
        from scripts.check_secrets import scan_diff
    except ImportError:
        return []
    return scan_diff(text, label)


def _snapshot(root: Path, findings: Sequence[Finding]) -> Dict[str, Optional[str]]:
    paths = {finding.path for finding in findings if finding.fixable}
    paths.add(str(regression_test_path(root).relative_to(root)).replace("\\", "/"))
    snapshots: Dict[str, Optional[str]] = {}
    for relative in paths:
        path = root / relative
        try:
            snapshots[relative] = path.read_text(encoding="utf-8") if path.is_file() else None
        except OSError:
            snapshots[relative] = None
    return snapshots


def _restore(root: Path, snapshots: Dict[str, Optional[str]]) -> None:
    for relative, original in snapshots.items():
        path = root / relative
        try:
            if original is None:
                if path.exists():
                    path.unlink()
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(original, encoding="utf-8")
        except OSError:
            continue


def _clean_before_repair(root: Path, allow_dirty: bool) -> None:
    if allow_dirty:
        return
    state_file = STATE_REL.as_posix()
    dirty = {path for path in dirty_paths(root) if path.replace("\\", "/") != state_file}
    if dirty:
        shown = ", ".join(sorted(dirty)[:8])
        raise ReforgeError(
            "The working tree is not clean enough to repair.",
            f"these paths hold uncommitted work Reforge did not make: {shown}",
            "commit or stash them, then run the audit again; the audit itself changed nothing.",
        )


def _execute_repairs(root: Path, findings: Sequence[Finding], add_tests: bool,
                     run_tests: bool, test_command: Optional[str],
                     gate_runner: Optional[GateRunner]) -> Tuple[List[Repair], Dict[str, object],
                                                                  Dict[str, object]]:
    targets = [finding for finding in findings if finding.fixable and not finding.repaired]
    if not targets:
        return [], {}, {}
    snapshots = _snapshot(root, targets)
    try:
        repairs = repair_findings(root, targets, add_tests=add_tests)
        applied = [repair for repair in repairs if repair.applied]
        tests: Dict[str, object] = {}
        gates: Dict[str, object] = {}
        if applied:
            issues = recheck_repairs(root, applied)
            allowed = repair_paths(repairs, root) + [STATE_REL.as_posix()]
            issues += review_patch(root, allowed, _scanner)
            if issues:
                raise ReforgeError(
                    "The repair patch failed review.",
                    "; ".join(issues[:6]),
                    "review the listed paths and re-run; the working tree was restored.",
                )
            command = test_command or default_test_command(root)
            if run_tests and command:
                tests = run_test_command(command, root)
                if not tests.get("passed"):
                    raise ReforgeError(
                        "The repaired tree failed its tests.",
                        f"`{command}` exited {tests.get('code')}: " +
                        " | ".join(str(line) for line in (tests.get("tail") or [])[-3:]),
                        "review the test output; the repair was rolled back.",
                    )
            if gate_runner is not None:
                passed, lines = gate_runner()
                gates = {"passed": passed, "lines": list(lines)}
                if not passed:
                    raise ReforgeError(
                        "The repaired tree failed the project's quality gates.",
                        " | ".join(str(line) for line in list(lines)[-4:]),
                        "review the gates; the repair was rolled back.",
                    )
        return repairs, tests, gates
    except ReforgeError:
        _restore(root, snapshots)
        raise
    except Exception as exc:
        _restore(root, snapshots)
        raise ReforgeError(
            "The repair could not be applied.",
            f"the repair engine stopped before a reviewable patch existed: {exc}",
            "review the finding evidence, fix the source or the generated test file by hand, "
            "then run the audit again; the working tree was restored.",
        ) from exc


def _payload(root: Path, mode: str, plan: StagePlan, findings: Sequence[Finding],
             repairs: Sequence[Repair], tests: Dict[str, object], gates: Dict[str, object]) -> Dict[str, object]:
    applied = sum(1 for repair in repairs if repair.applied)
    return {
        "mode": mode,
        "root": str(root),
        "stage": plan.stage,
        "plan": plan.as_dict(),
        "counts": summarize(findings),
        "findings": [finding.as_dict() for finding in findings],
        "repairs": [repair.as_dict() for repair in repairs],
        "repaired": applied,
        "tests": tests,
        "gates": gates,
        "summary": (f"stage {plan.stage}: {len(findings)} finding(s), "
                    f"{applied} repaired, window {plan.window}"),
    }


def run_pipeline(root: Path, mode: str = "run", add_tests: bool = True,
                 run_tests: bool = True, test_command: Optional[str] = None,
                 gate_runner: Optional[GateRunner] = None,
                 allow_dirty: bool = False) -> Dict[str, object]:
    """Audit the next stage (`audit`), repair the last one (`fix`), or do both (`run`)."""
    root = Path(root)
    state = load_state(root)
    if mode == "fix":
        last = state.get("last_audit")
        if not isinstance(last, dict):
            raise ReforgeError(
                "There is no audit to fix.",
                "`fix` repairs the findings of the latest completed audit.",
                "run `audit` or `run` first; nothing was changed.",
            )
        findings = [finding_from_dict(item) for item in unrepaired_findings(state)]
        if not findings:
            raise ReforgeError(
                "The latest audit has no unrepaired findings.",
                "every recorded finding was repaired or had no safe automatic edit.",
                "run the next `audit`; nothing was changed.",
            )
        plan = StagePlan(stage=int(last.get("stage") or 0), window=int(last.get("window") or 0),
                         commits=(), new_shas=tuple(last.get("new_commits") or []),
                         prior_shas=tuple(last.get("prior_commits") or []))
        _clean_before_repair(root, allow_dirty)
        repairs, tests, gates = _execute_repairs(root, findings, add_tests, run_tests,
                                                 test_command, gate_runner)
        last["repairs"] = [repair.as_dict() for repair in repairs]
        last["tests"] = tests
        last["gates"] = gates
        save_state(root, state)
        mark_repairs(root, state, repairs)
        return _payload(root, mode, plan, findings, repairs, tests, gates)

    plan = plan_next_stage(root, state)
    findings = audit_window(root, plan, state.get("history") or [])
    if mode == "audit":
        entry = entry_from_stage(plan, findings, [])
        record_stage(root, state, entry)
        return _payload(root, mode, plan, findings, [], {}, {})
    if mode != "run":
        raise ReforgeError(
            f"Unknown mode '{mode}'.",
            "Reforge supports audit, fix and run.",
            "run `--help` to list the valid commands.",
            exit_code=2,
        )
    _clean_before_repair(root, allow_dirty)
    repairs, tests, gates = _execute_repairs(root, findings, add_tests, run_tests,
                                             test_command, gate_runner)
    entry = entry_from_stage(plan, findings, repairs, tests, gates)
    record_stage(root, state, entry)
    mark_repairs(root, state, repairs)
    return _payload(root, mode, plan, findings, repairs, tests, gates)


def status_payload(root: Path) -> Dict[str, object]:
    root = Path(root)
    state = load_state(root)
    stage = last_stage(state)
    last = state.get("last_audit") if isinstance(state.get("last_audit"), dict) else None
    pending = len(unrepaired_findings(state)) if last else 0
    return {
        "root": str(root),
        "head": head_sha(root),
        "stage": stage,
        "next_stage": stage + 1,
        "next_window": window_for_stage(stage + 1),
        "audited_commits": len(state.get("audited_commits") or []),
        "pending_findings": pending,
        "last_audit": last,
        "history": len(state.get("history") or []),
    }


def report_payload(root: Path) -> Dict[str, object]:
    root = Path(root)
    state = load_state(root)
    return {
        "root": str(root),
        "stage": last_stage(state),
        "audited_commits": list(state.get("audited_commits") or []),
        "history": list(state.get("history") or []),
    }
