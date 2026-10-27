# Changelog

All notable changes to Aegean Reforge are recorded here.

## [0.2.1] - 2026-10-27

- `reforge-sync.json` names the shipped package, shim, standalone target and marker.
- Synchronization refuses a two-sided edit and records the last synced hashes.
- README/CHANGELOG regeneration keeps the standalone lifecycle current.

## [0.2.0] - 2026-10-27

- Independent, configurable audit runs: `--start`, `--step`, `--stop`, `stop`, `resume`,
  `settings` and `runs`, with per-run history.
- Per-project run lock: different projects audit concurrently; a second operation on one project
  is refused.
- Schema-2 state with schema-1 migration and compact run summaries.

## [0.1.0] - 2026-10-27

- Initial shipped source: progressive commit-window auditing, evidence-backed findings, safe
  repairs, generated regression tests, patch review, bounded test execution and bidirectional
  synchronization with AIKit.
