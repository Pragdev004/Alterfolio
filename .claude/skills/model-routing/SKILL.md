---
name: model-routing
description: Classify a task and recommend the cheapest reliable model and effort (Haiku/Sonnet/Opus), and say when to escalate. Use before delegating work to a subagent or when deciding whether a task needs a stronger model. Advisory; it cannot change the model of a running session.
---

# Model routing (Alterfolio V2)

Advisory only. A skill cannot switch the model of the session it runs in. The supported mechanisms are:
- `/model` (user-run) or the `opusplan` setting (Opus while planning, Sonnet while executing; already set in `.claude/settings.local.json`).
- The Agent tool's `model` parameter (`haiku` | `sonnet` | `opus`) when spawning a subagent. This is the only per-task switch.
- Never use Fable (global rule). Do not spawn agents just because they are available.

## Classify, then route
| Task shape | Model | Effort |
| --- | --- | --- |
| Find/read files, list usages, count tests, mechanical rename, simple test scaffold | Haiku | low |
| Ordinary feature step with an approved spec, tests, routine debugging, docs sync | Sonnet | medium |
| Substantial engineering across several modules, flaky or non-obvious failure | Sonnet | high |
| Architecture or boundary changes, security/data-integrity reasoning, point-in-time/leakage proofs, final critical review | Opus | high |
| Genuinely open-ended, long-horizon or irreversible design | Opus | xhigh (rare) |

## Escalate only when
1. Two focused attempts failed and the cause is still unclear (Sonnet -> Opus, same context, narrowed question).
2. The change touches an invariant in `CLAUDE.md` section 6 (import boundaries, Decimal money, point-in-time, user isolation).
3. A review must find what the author could not (use Opus for the reviewer, not the author).
Do not escalate for size alone; split the work instead. Send a subagent only the files and facts it needs.

## Project defaults
- Quant/backtest steps with an approved spec: Sonnet medium, tests first. Leakage/determinism review: Opus high.
- Doc status edits and index updates: Haiku low.
- Never run live-database or paid-API checks to "test" a routing choice.
