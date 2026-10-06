# EnterpriseOS frontend

React + TypeScript + Vite. Ролевые маршруты, бизнес-экраны и account flow
используют backend permissions / allowed_actions / ActionContext.

## Команды

Из `frontend` после установки зависимостей:

```bash
npm run dev
npm run test
npm run lint
npm run build
```

`test` запускает существующие Node tests из `tests/*.test.ts`; `build` выполняет
TypeScript check и production Vite build. Два baseline ESLint errors в
`src/contexts/AuthContext.tsx` учитываются отдельно от lint изменённых файлов.

Продуктовые правила и текущий baseline — в
[Codex Context](../docs/CODEX_CONTEXT.md) и
[Supply roadmap](../docs/ROADMAP_STAGE_3_SUPPLY_v0.1.0.md).
