# GMS MCP Codebase Review — 2026-07-11

## Review metadata

- Repository: `Ampersand-Game-Studios/gms-mcp`
- Branch: `dev`
- Commit: `ccf50c39bcdf398932806d2fed02cd85f2b40263`
- Reviewer: OpenAI Codex (GPT-5; effort setting not exposed by the runtime)
- Prior review: none; this entry establishes the baseline

## Score

| Surface | Score |
| --- | ---: |
| Structural coherence | 1.0/2 |
| Local code clarity | 1.0/2 |
| Testability and validation safety | 1.5/2 |
| MCP/tool ergonomics and GameMaker correctness | 1.0/2 |
| Risk concentration | 0.5/2 |
| **GMS MCP overall** | **5/10** |

The repository is far beyond a disposable prototype: it has strong automated coverage, real GameMaker compilation evidence, typed MCP validation, transactions, raw-CLI policy gates, and a recently improved module layout. It remains a functional-but-rough internal tool rather than a solid agent platform because concurrent direct calls can cross project roots, agent documentation advertises unsupported collision-event syntax, root-level asset creation is the default, and destructive/refactor workflows rely on broad heuristic rewrites and whole-project rollback.

## Strong evidence

- Full Python suite passed: 969 tests plus 229 subtests; generated quality report records 1,198 checks and 88.32% statement coverage, above the 85% overall and 50% per-module gates.
- Ruff passed; Pyright passed with zero errors and two dynamic-`__all__` warnings.
- All 98 MCP tools registered; the deterministic 12-tool MCP smoke passed.
- A required real GameMaker smoke passed against a temporary copy of the bundled blank project on runtime `2024.14.4.268`: high-risk sprite creation compiled, frame mutation deferred, and the verification flush compiled.
- Python sdist and wheel built successfully; telemetry worker tests passed and Biome reported warnings only.
- Typed write-operation models, atomic JSON writes, raw `gm_cli` read-only allowlisting, destructive CLI fallback blocking, transaction annotations, and opt-in telemetry are implemented rather than merely documented.

## Top findings

1. **Concurrent MCP calls can target the wrong project.** The installed MCP server starts each request in an AnyIO task group, but `gms_mcp.server.direct._pushd`, CLI helpers, and output capture mutate process-global cwd/stdout. A two-call probe confirmed one handler observed the other project, the second observed the repository root, and cwd was not restored. There is also no per-project mutation lock.
2. **Rollback can erase unrelated concurrent work.** `GameMakerProjectTransaction.rollback()` deletes every project child except a small ignore set, then restores its snapshot. An IDE save, another agent mutation, or an unrelated file created after `begin()` can be removed. The full-project copy/hash strategy is also expensive and dereferences symlinks during backup.
3. **Collision events are an agent-facing broken promise.** The bundled skill/reference docs instruct `collision:o_wall`; MCP validation requires the suffix to be an integer, `event_helper` parses it as an integer, and emitted events set `collisionObjectId` to `None`.
4. **The tool defaults encourage unorganised GameMaker assets.** Creation tools default `parent_path=""`, and `BaseAsset` converts that to the project `.yyp` parent. The setup-object skill says never use the project root, while setup-room examples omit parent paths.
5. **Rename/delete safety is heuristic and broad.** Rename performs regex line rewrites across GML without parsing strings/comments and then runs auto-maintenance with `fix_issues=True`. Safe-delete reference cleanup replaces matching GML tokens with `undefined`. These operations are transactional, but they can still commit unintended unrelated edits when validation/compile succeeds.
6. **Execution policy registration and dispatch disagree.** Dispatch derives up to three non-flag CLI tokens, so calls such as event add and workflow duplicate include operand values in the policy key and miss the registered `event-add` / `workflow-duplicate` policies. The smoke report demonstrates `gm_event_add` taking the subprocess path despite the direct policy.
7. **The subprocess runner does not actually create a process group.** `_spawn_kwargs()` returns no platform options, yet timeout cleanup first calls `killpg(proc.pid)`. It normally falls back to terminating only the immediate child, so grandchildren can survive despite the process-tree claim.
8. **Release safety is not enforced.** CI and PyPI publishing are separate workflows triggered by the same `main` push; publishing does not depend on CI success. CI itself runs only for `main` pushes/PRs, not ongoing `dev` or `pre-release` work. `RELEASING.md` says dev/RC branches publish even though `publish.yml` only watches `main` and tags.
9. **The impressive test count overstates semantic breadth.** The MCP validation report counts tool-name references in test source, most tests disable compile verification, the real smoke exercises two mutations, and there are no concurrency/cross-project tests. The quality run also removed the newline from tracked `test_project.yyp`; the review restored it.
10. **Dependency/API drift remains exposed.** Runtime dependencies have only lower bounds, `uv.lock` is ignored, `fastmcp` is a declared/import-checked dependency but production code imports the SDK's `mcp.server.fastmcp`, and the server patches private MCP members (`_handle_request`, `_tool_manager`).

## What blocks the next levels

- **8/10:** eliminate process-global cwd/stdout mutation; serialize per-project writes; replace destructive snapshot rollback with conflict-aware file journaling; make parent folders safe by default; and contract-test every bundled agent workflow against real schemas.
- **9/10:** replace regex refactors with GameMaker/GML-aware semantic edits; enforce real GameMaker fixtures across supported versions; curate the 98-tool surface; and make publish depend on the complete release gate.
- **10/10:** reserved for long-term reference-quality evidence: fault injection, concurrent multi-agent stress, cross-version format fixtures, migration guarantees, and operational release history with no hidden manual safety assumptions.

## Bottom line

GMS MCP is useful and well tested for serialized, version-controlled GameMaker work with smart compile verification enabled. It is not safe enough for concurrent or multi-agent mutation of the same live workspace, and rename/delete/cleanup operations should not be treated as trustworthy autonomous refactors until the cwd, locking, rollback, and semantic-edit issues are fixed.

## Score delta

Baseline review; no prior score or delta exists.
