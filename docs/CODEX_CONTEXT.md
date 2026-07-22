# Codex Context

## Current stage

Stage 2 — Automation Core — completed (100%).

The next stage must be taken strictly from the current roadmap. At the current
roadmap version, this is Stage 3 — Supply.

## Current state

- Roadmap: `docs/ROADMAP_v0.12.0.md`.
- Branch and HEAD: `main`, `de3dfd43c3196f560f1a00bda2690bb0e43c8323`.
- Server, GitHub, and Mac checkouts are synchronized at this HEAD.
- Database migrations are at `20260722_0004`.
- Backend suite: 307/307 passed.
- Frontend tests: 36/36 passed.
- Frontend production build passed.
- The end-to-end `smoke_test` through n8n reaches `SUCCEEDED`.
- n8n and n8n-postgres are healthy.
- An n8n backup was created and validated; restore tooling and a retention policy are in place.

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

## Automation Core completion

- Automation schedule CRUD.
- Scheduler and timing engine.
- Automation execution model.
- Transactional outbox.
- Persistent automation worker.
- Retry, timeout recovery, and protected idempotent callback flow.
- Idempotency-key protection for external side effects.
- Execution history and safe user-facing statuses and errors.
- Audit log and platform-admin diagnostics.
- Automation type catalog.
- End-to-end `smoke_test` through the importable n8n workflow.
- Health checks for n8n and n8n-postgres.
- n8n backup/restore tooling and retention.

## Known limitations

- Two pre-existing ESLint errors remain in `frontend/src/contexts/AuthContext.tsx`.
- Visual polish for tables and selects and broader responsive UI work are
  intentionally assigned to the future design stage and are not Automation
  Core debt.

## Deferred

- PWA.
- Web Push.
- Notification center.
- Apple Calendar.
- Table, select, and responsive UI polish (roadmap design stage).
- Mascots.
- Light and dark theme.

## Working rules

- Work only on the requested task.
- Do not update roadmap or documents unless explicitly requested.
- Do not modify `.env`, secrets, or infrastructure credentials.
- Do not commit or push unless explicitly instructed.
- Run only relevant tests during development.
- Keep the final report concise.
