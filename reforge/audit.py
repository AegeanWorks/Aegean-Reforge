"""Progressive 3/6/9 commit-window analysis with cross-commit interaction evidence."""

from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from reforge.detectors import detect_source, symbols_in_source
from reforge.errors import ReforgeError
from reforge.git_history import (
    added_lines,
    changed_files,
    commit_count,
    commit_info,
    commit_window,
    file_at,
    is_git_repo,
)
from reforge.model import CommitInfo, Finding, StagePlan

STAGE_STEP = 3


def window_for_stage(stage: int) -> int:
    """The documented progression: stage 1 sees 3 commits, stage 2 sees 6, stage 3 sees 9."""
    return STAGE_STEP * stage


def plan_next_stage(repo: Path, state: Dict[str, object]) -> StagePlan:
    """The next window, its newly included commits and the already-audited overlap."""
    if not is_git_repo(repo):
        raise ReforgeError(
            f"{repo} is not a git repository.",
            "Reforge audits commits, so it needs a repository with at least one commit.",
            "run `git init` and commit the code first, or point the command at the repository root.",
        )
    total = commit_count(repo)
    if total == 0:
        raise ReforgeError(
            "The repository has no commits.",
            "an empty history has nothing to audit.",
            "commit the code, then run the audit again.",
        )
    stage = int(state.get("stage") or 0) + 1
    wanted = window_for_stage(stage)
    commits = commit_window(repo, min(wanted, total))
    audited = set(state.get("audited_commits") or [])
    new_shas = tuple(commit.sha for commit in commits if commit.sha not in audited)
    # Every earlier analysed commit stays in view for interaction evidence, not only the overlap
    # inside this window; the window itself still follows the documented 3/6/9 progression.
    new_set = set(new_shas)
    prior_shas = tuple(sha for sha in (state.get("audited_commits") or []) if sha not in new_set)
    if not new_shas:
        raise ReforgeError(
            f"No new commits for stage {stage}.",
            f"its window is the newest {min(wanted, total)} commits and every one was already audited.",
            "push or commit more work, then run the next stage; nothing was changed.",
        )
    return StagePlan(stage=stage, window=min(wanted, total), commits=tuple(commits),
                     new_shas=new_shas, prior_shas=prior_shas)


def _prior_context(repo: Path, plan: StagePlan, history: Sequence[Dict[str, object]]
                   ) -> Tuple[Dict[str, CommitInfo], Dict[Tuple[str, str], str],
                              Dict[Tuple[str, str, str], str], Dict[Tuple[str, str], int]]:
    by_sha = {commit.sha: commit for commit in plan.commits}
    paths: Dict[str, CommitInfo] = {}
    symbols: Dict[Tuple[str, str], str] = {}
    findings: Dict[Tuple[str, str, str], str] = {}
    repairs: Dict[Tuple[str, str], int] = {}
    for sha in plan.prior_shas:
        info = by_sha.get(sha) or commit_info(repo, sha)
        if info is None:
            continue
        for status, path in changed_files(repo, sha):
            if status == "D" or not path.endswith(".py"):
                continue
            paths[path] = info
            source = file_at(repo, sha, path)
            if not source:
                continue
            touched = added_lines(repo, sha, path)
            try:
                for name, start, end in symbols_in_source(source):
                    if touched.intersection(range(start, end + 1)):
                        symbols[(path, name)] = sha
            except SyntaxError:
                continue
    for entry in history:
        for item in entry.get("findings") or []:
            findings[(item.get("path", ""), item.get("symbol", ""),
                      item.get("code", ""))] = item.get("commit", "")
        for item in entry.get("repairs") or []:
            if item.get("applied"):
                key = (item.get("path", ""), item.get("code", ""))
                repairs[key] = max(repairs.get(key, 0), int(entry.get("stage") or 0))
    return paths, symbols, findings, repairs


def _interaction(finding: Finding, prior: Tuple[Dict[str, CommitInfo],
                                                Dict[Tuple[str, str], str],
                                                Dict[Tuple[str, str, str], str],
                                                Dict[Tuple[str, str], int]]) -> Tuple[str, bool]:
    paths, symbols, findings, repairs = prior
    if (finding.path, finding.symbol) in symbols:
        sha = symbols[(finding.path, finding.symbol)]
        return (f"{finding.symbol or 'the symbol'} was introduced or changed earlier by {sha[:12]}", True)
    if (finding.path, finding.symbol, finding.code) in findings:
        sha = findings[(finding.path, finding.symbol, finding.code)]
        return f"the same rule at the same symbol was already analysed in {sha[:12]}", True
    stage = repairs.get((finding.path, finding.code))
    if stage:
        return f"a repair for this rule in this file was applied at stage {stage}", True
    if finding.path in paths:
        sha = paths[finding.path].sha
        return f"the file was also changed earlier by {sha[:12]}", False
    return "", False


def audit_window(repo: Path, plan: StagePlan, history: Sequence[Dict[str, object]] = ()) -> List[Finding]:
    """Deeply inspect every line the new commits add, and tie it to prior analysed work."""
    prior = _prior_context(repo, plan, history)
    by_sha = {commit.sha: commit for commit in plan.commits}
    findings: List[Finding] = []
    for sha in reversed(plan.new_shas):
        info = by_sha[sha]
        for status, path in changed_files(repo, sha):
            if status == "D" or not path.endswith(".py"):
                continue
            source = file_at(repo, sha, path)
            if source is None:
                continue
            touched = added_lines(repo, sha, path)
            parsed = detect_source(path, source, sha)
            for finding in parsed:
                if status != "A" and finding.line not in touched:
                    continue
                interaction, strong = _interaction(finding, prior)
                if interaction:
                    finding = Finding(
                        **{**finding.as_dict(), "interaction": interaction,
                           "category": "regression" if strong else finding.category}
                    )
                findings.append(finding)
    return _ordered(findings)


def _ordered(findings: Iterable[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda item: (item.commit, item.path, item.line, item.code))


def summarize(findings: Sequence[Finding]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for finding in findings:
        counts[finding.category] = counts.get(finding.category, 0) + 1
    return counts
