# Aegean Reforge

> Progressive, evidence-backed Git history auditing and autonomous safe repair.

Aegean Reforge walks a repository's history in stages: it audits the newest 3 commits, repairs
what it can prove, and after those repairs are pushed it audits the newest 6 (the previous 3 plus
3 new), then 9, and so on. Every stage re-examines the overlap, so a new commit is judged against
the changes already analysed.

## Quick Start

- **Runtime Prerequisites**: Python 3.10+ and `git` (standard library only).
- **Canonical Regression Shield Gate**:

```bash
python -m unittest discover tests
```

## Why It Is Safe

- Findings must carry evidence: the exact commit, path, line and source text.
- Only small, mechanical repairs are automatic (bare `except`, mutable defaults, unsafe
  `yaml.load`, disabled TLS verification, `shell=True` with an argument list).
- Every repair is re-detected, the actual `git diff` is reviewed, and the project's tests run.
  A red gate rolls the patch back before it is recorded.
- Repairs are committed explicitly and pushed without force only when `--push` is passed.

## Commands

```bash
python reforge.py audit <repo-or-project> --json
python reforge.py run <repo-or-project>
python reforge.py run <repo-or-project> --push
python reforge.py status <repo-or-project>
python reforge.py report <repo-or-project>
python reforge.py repo init [--path <dir>]
python reforge.py repo sync [--direction push|pull] [--force]
```

The audit state lives in `.aikit/reforge.json` and records each stage, every audited commit, the
findings, repairs, test results and gate results.

## License

Free for personal use under the Aegean License 1.1 (AL-1.1); see [LICENSE](LICENSE). Commercial
use needs the Aegean Commercial License 1.0 (ACL-1.0); see [COMMERCIAL.md](COMMERCIAL.md).
