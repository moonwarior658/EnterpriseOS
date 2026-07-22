# Codex Context

## Current stage

Stage 2 — Automation Core.

## Architecture

Execution flow:

EnterpriseOS  
→ AutomationProvider  
→ transactional outbox  
→ automation worker  
→ n8n  
→ callback  
→ EnterpriseOS

Rules:

- EnterpriseOS is the source of truth.
- Business logic stays inside EnterpriseOS.
- n8n is an execution orchestrator only.
- Reuse the existing dispatch and transactional outbox flow.
- Do not duplicate scheduler, dispatch, outbox, retry, worker, or callback logic.

## Implemented

- Automation schedule CRUD.
- Scheduler and timing engine.
- Automation execution model.
- Transactional outbox.
- Persistent automation worker.
- n8n provider and callback flow.
- Schedule list UI.
- Create and edit schedule UI.
- Enable and disable schedule.
- Manual schedule execution.
- Safe Russian user-facing errors.
- Relevant backend and frontend tests.

## Current task

Implement full automation execution history.

Expected result:

- List executions for a selected schedule.
- Show status, start time, finish time, duration, and safe error text.
- Do not expose raw payloads, execution IDs, webhook URLs, or n8n internals.
- Reuse existing backend models and contracts where possible.
- Do not add audit log, diagnostics, or notification delivery in the same task.

## Next tasks

1. Batch endpoint for latest executions.
2. User-facing execution status classification.
3. External side-effect deduplication.
4. Audit log.
5. Platform-admin diagnostics.
6. n8n backup and monitoring.
7. Automation type catalog.
8. Test notification flow.

## Known limitations

- The only confirmed automation type is `smoke_test`.
- There is no automation type catalog yet.
- Latest execution status is not polled after manual launch.
- Full execution history is not implemented yet.
- Two pre-existing ESLint errors remain in `frontend/src/contexts/AuthContext.tsx`.

## Deferred

- PWA.
- Web Push.
- Notification center.
- Apple Calendar.
- UI polish.
- Mascots.
- Light and dark theme.

## Working rules

- Work only on the requested task.
- Do not update roadmap or documents unless explicitly requested.
- Do not modify `.env`, secrets, or infrastructure credentials.
- Do not commit or push unless explicitly instructed.
- Run only relevant tests during development.
- Keep the final report concise.
