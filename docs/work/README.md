# Project work

Keep current work here, one file per workstream. Completed history lives in
[archive/](archive/2026-10-18-progress.md); setup and technical documentation
remain in the existing guides under `docs/`.

## Current status

No implementation milestone is currently in progress. Release milestones 1–4
are complete, including public installation and owner-verified reboot startup.

| Workstream | Status | Next step |
| --- | --- | --- |
| [Release delivery and maintenance](release-maintenance.md) | Milestones 1–4 complete; milestone 5 planned | Review upgrade/rollback work before starting implementation. |
| [Architecture refactoring backlog](../refactoring-targets.md) | Targets 1–3 complete; targets 4–9 proposed | Select and detail a target when requested. |

## Completed work

[Progress archive through 18 October 2026](archive/2026-10-18-progress.md)
preserves the original investigation and implementation record: authentication,
SDK/encrypted streams, live grid and quality, History, exports, CI/test
refactoring, release packaging, public installation and reboot verification.
It retains commit references, checks and private evidence paths. Statements in
that snapshot reflect when they were written, rather than current task status.

## Maintaining work records

- Start or resume a workstream in its own `docs/work/<topic>.md` file. Give it
  a status (`planned`, `active`, `blocked` or `completed`), goal, current state,
  next step and verification results. Use dates and commit references when useful.
- Keep this index short: update the status and next step, rather than appending
  a running log. Distinguish planned work from work that has actually started.
- Link to existing design plans and operational guides. Record decisions and
  results here without duplicating those documents or private credentials/logs.
- On completion, summarize the result and verification, move the work file into
  `archive/`, and update its links and this index. Create a separate file for
  a later workstream rather than reopening a large historical log.
- Check relative links when moving files. Keep setup/agent instructions current
  when behavior changes; `progress.md` is only a compatibility pointer.
