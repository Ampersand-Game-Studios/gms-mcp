# GMS MCP Post-Remediation Codebase Review — 2026-07-11

## Review metadata

- Repository: `Ampersand-Game-Studios/gms-mcp`
- Branch: `dev`
- Baseline commit: `ccf50c39bcdf398932806d2fed02cd85f2b40263`
- Reviewed state: the uncommitted remediation working tree on that commit
- Reviewer: OpenAI Codex (GPT-5; effort setting not exposed by the runtime)
- Prior review: `2026-07-11-codebase-review.md`, 5/10
- Commit history since the baseline: none; every score increase below is supported by the inspected working-tree changes and fresh validation evidence

## Score

| Surface | Prior | Current | Delta | Why it moved |
| --- | ---: | ---: | ---: | --- |
| Structural coherence | 1.0/2 | 1.8/2 | +0.8 | Direct execution is isolated, tool registration is profile-based, mutation and host-operation locks have explicit boundaries, and package-owned assets have one resolver. |
| Local code clarity | 1.0/2 | 1.8/2 | +0.8 | Collision/event models, semantic reference handling, verification policy, process lifecycle, and release certification are explicit modules with typed contracts and focused tests. |
| Testability and validation safety | 1.5/2 | 2.0/2 | +0.5 | 1,311 checks pass, coverage is 87.30% with every module above 50%, all 96 tools have executed smoke coverage, and fault/concurrency/cross-version tests are enforced. |
| MCP/tool ergonomics and GameMaker correctness | 1.0/2 | 2.0/2 | +1.0 | The default surface is a curated 29-tool profile, the full 96-tool surface passes, parents/collisions/rooms/events compile on genuine 2024 and 2026 projects, and raw CLI escape hatches are gone. |
| Risk concentration | 0.5/2 | 1.4/2 | +0.9 | Conflict-aware journals, per-project locks, a host-wide GameMaker lease, process groups, bounded logs, fail-closed release gates, and frozen dependencies now contain the main failure modes. The remaining deduction is operational history and the size of a few mutation modules. |
| **GMS MCP overall** | **5/10** | **9/10** | **+4** | **All ten actionable roast findings are closed. The rubric reserves 10/10 for longitudinal release and migration evidence that a local remediation run cannot manufacture.** |

## Top-line rating

**GMS MCP: 9/10.** It has moved from a functional but unsafe internal tool to exemplary GameMaker agent infrastructure: concurrent calls are isolated, writes are conflict-aware and reversible, GameMaker itself certifies the risky mutations across two genuinely distinct format generations, and the release/package/plugin paths fail closed. The remaining point is evidence over time, not another locally discoverable P0-P2 defect.

## Verification evidence

| Gate | Final evidence |
| --- | --- |
| Python suite | 1,088 tests plus 223 subtests; 1,311/1,311 checks passed, no skips, failures, or errors |
| Coverage | 87.30% overall; 85% overall and 50% per-module gates passed with no exclusions |
| Static quality | Ruff format and lint clean; Pyright 0 errors/0 warnings; `uv lock --check` and `git diff --check` clean |
| MCP default profile | 29/29 tools executed and passed |
| MCP complete profile | 96/96 tools executed and passed; runtime/source registration parity is 96/96 |
| Contention | Two independent projects each passed compile/run/status/stop, 4/4, while started concurrently |
| Live lifecycle | Project A remained running under its original runner PID while project B compiled; A then stopped cleanly |
| GameMaker 2024 | IDE `2024.14.3.217`, runtime `2024.14.4.268`, 9/9 required mutation/compile checks passed |
| GameMaker 2026 LTS | IDE `2026.0.0.16`, runtime `2026.0.0.23`, 9/9 required mutation/compile checks passed |
| Release certification | Distinct source paths and SHA-256 hashes verified; `gm-2024` and `gm-2026-lts` certification passed |
| Distribution | Clean sdist and wheel built; fresh Python 3.13 install exposed 29 core tools and contained the skills/hooks bundle; stale requirements were absent |
| Claude plugin | Marketplace/plugin validation passed; plugin-owned `gms` MCP server connected |
| Telemetry worker | Node tests 2/2 passed; Biome check clean |
| Fixture hygiene | Bundled `BLANK GAME` source fixture unchanged; no accidental generated `mcp_smoke.yyp` remains |

## Original roast findings — line-by-line closure audit

### 1. Concurrent MCP calls can target the wrong project — closed

- Typed direct handlers now execute in disposable, timeout-bounded worker processes; the server process no longer mutates cwd, argv, environment, stdout, or stderr for a request.
- CLI subprocesses receive explicit project roots and working directories.
- Cross-project concurrency tests prove captured output and cwd cannot bleed between calls.
- Mutations also take a per-project thread/process lock, while GameMaker compile/run start/stop operations take a cooperating host-wide lease.

### 2. Rollback can erase unrelated concurrent work — closed

- Whole-project deletion/restore rollback was replaced by a path journal.
- The journal records created, modified, and deleted paths plus ownership fingerprints.
- Rollback only touches transaction-owned paths and fails closed on ownership conflicts instead of erasing external work.
- Cancellation, nested compile verification, symlink/path boundaries, cross-thread contention, and cross-process contention have focused regression coverage.

### 3. Collision events are an agent-facing broken promise — closed

- One event model now parses and emits collision events by object name.
- `collisionObjectId` is resolved to the target object resource instead of being emitted as `None`.
- Exact validators reject malformed collision metadata and accept 2024/2026 serializer envelopes.
- Collision target rename updates schema and references; both real GameMaker fixtures compile the result.

### 4. Tool defaults encourage unorganised assets — closed

- An omitted parent now creates/reuses the correct logical GameMaker folder for that asset type.
- New assets no longer silently use the `.yyp` as their parent.
- Room ordering and folder resources are updated deliberately.
- Skills, references, examples, and tests agree with the safe default-parent contract.

### 5. Rename/delete safety is heuristic and broad — closed

- Reference edits are token-aware: strings, comments, regions, member scopes, struct keys, enum members, and local shadowing are distinguished.
- Ambiguous edits abort before mutation.
- Safe delete no longer writes `undefined` into dependent code.
- Rename/delete report exact planned changes and commit only after transaction validation/compile policy succeeds.

### 6. Execution policy registration and dispatch disagree — closed

- Dispatch keys are derived from command structure rather than operand values.
- Event/workflow operations now hit their registered direct policies.
- Wrapper translation and direct/subprocess parity are contract-tested across the complete registered surface.

### 7. The subprocess runner does not create a process group — closed

- POSIX children start in a new session; Windows children use the corresponding process-group creation flags.
- Timeout/cancellation cleanup targets the process tree, waits, escalates, and reports any PIDs it could not terminate.
- Logs are bounded and durable rather than unbounded in-memory captures.
- Public runner cwd and macOS runner-PID tracking are covered directly.

### 8. Release safety is not enforced — closed

- CI covers `dev`, `pre-release`, and `main`.
- Publish consumes the exact successful CI SHA and its immutable build/real-GameMaker artifacts rather than racing a parallel push workflow.
- Publication fails closed unless both distinct GameMaker fixtures pass the certification gate.
- Release documentation matches the actual branch/channel workflow.

### 9. Test count overstates semantic breadth — closed

- The report now separates static references from executed dedicated smoke calls.
- Every one of the 96 registered tools executes against an isolated portable project; the default 29-tool profile also executes independently.
- Transaction fault injection, direct-worker isolation, process cleanup, semantic rename/delete, two-project contention, and an active-run-versus-compile lifecycle are tested.
- Real GameMaker certification now covers nine structural checks on both 2024 and 2026-authored projects, including collision and room-order mutations.

### 10. Dependency/API drift remains exposed — closed

- Runtime and development dependencies have upper bounds; `uv.lock` is the authoritative lockfile and its frozen check passes.
- The unused `fastmcp` dependency path and stale `src/gms_mcp/requirements.txt` were removed.
- Server construction and tool inspection use public MCP APIs; private `_handle_request` and `_tool_manager` patching is gone.
- Wheel/sdist construction packages the canonical skills and hooks, and a fresh out-of-repository Python 3.13 install is exercised.

## Additional defects found and closed during remediation

- The default core smoke originally depended on optional asset-creation tools for scenario setup. Preconditions now create isolated fixture state directly, so core passes independently at 29/29.
- Concurrent GameMaker projects were empirically able to collide at the host runtime. A scoped host-wide lease now covers compile and durable run-start/stop barriers without locking for the game lifetime.
- The 2026 LTS Igor binary reproduced a .NET serializer/compiler concurrency crash on this host. Igor children now default to one reported .NET processor, with a validated `GMS_MCP_IGOR_PROCESSOR_COUNT` override; transient state is also cleared before confirmed infrastructure retries. The final 2026 certification passes without a shell-only override.
- The final formatter sweep found five baseline files outside Ruff format. They are normalized, and the repository-wide format check now passes.

## Praise

- Safety is structural rather than advisory: explicit transaction ownership, conflict detection, host/process locks, timeouts, and compile gates enforce the intended behavior.
- GameMaker correctness is backed by the actual 2024 and 2026 compilers, not inferred from JSON snapshots alone.
- The MCP surface is now legible to agents: a focused core, capability discovery, typed named tools, and no broad raw command escape hatch.
- Release evidence is tied to the exact artifact-producing SHA and fails closed on missing or duplicate fixtures.
- Packaging is self-contained across source checkouts, wheels, and wheels rebuilt from sdists.

## What keeps it from 10/10

- No push-triggered CI run has yet accumulated against this uncommitted working tree.
- No PyPI promotion from the new artifact chain has yet established a successful operational release history.
- Migration guarantees need evidence from repeated upgrades of real external projects over time, not a one-session fixture matrix.
- `transactions.py`, `workflow.py`, and `reference_scanner.py` remain large concentration points even though their dangerous paths are now isolated and heavily tested.

These are longitudinal and operational criteria from the original rubric. Calling the repository 10/10 now would fabricate evidence that does not exist.

## Bottom line

GMS MCP is now safe and useful for autonomous, agent-driven GameMaker work within the tested operating envelope. Normal mutations are isolated, journaled, validated, and compiled according to risk; concurrent projects no longer share process state or GameMaker critical sections; and release outputs cannot outrun their evidence. There are no remaining actionable P0, P1, or P2 findings from the baseline roast.

## Score delta

**5/10 → 9/10 (+4).** Every increase is tied to inspected working-tree changes and fresh executable evidence above. The same `dev` commit remains checked out; no commit, push, deployment, or publication was performed.
