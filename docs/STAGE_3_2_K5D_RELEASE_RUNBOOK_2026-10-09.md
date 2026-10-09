# K5D — release и короткий Windows runbook

09.10.2026. Commit/push разрешены отдельным release-заданием; production не обновляется
агентом. Команды ниже подготовлены для оператора, на Windows здесь не выполнялись.

Review: UI/API защищены отдельными capabilities; source UUID, immutable K5B
versions/observations и audit confirmations сохранены; INCOMPLETE/CONFLICT/stale
не подтверждаются, production readiness остаётся false. Новых models/DDL нет.
Alembic head **20261009_0078**: K5D **не требует миграции**. `alembic upgrade`
для этого релиза не запускать. Actual production HEAD/head проверяет оператор.

В release входят только 20 K5D файлов. Исходные untracked K5A report/evidence
исключены. Backend/full и PG tests, frontend tests/build/changed-file lint
подтверждены hash evidence. Бизнес-приёмка iikoOffice и browser smoke ещё открыты.

## Deployment — PowerShell 7, C:\eos

Выполнить после отдельного решения о deployment. Дождаться окончания текущих
ручных recipe runs; во время замены контейнеров не запускать новые обновления.
При другом baseline, dirty tracked-файлах или head ≠ 0078 — STOP для нового review.
Untracked-файлы сохранить. `.env`, PostgreSQL, n8n и proxy не изменять.

```powershell
Set-Location C:\eos
$ErrorActionPreference = 'Stop'
$Target = Read-Host 'Полный SHA K5D из передачи'
if ($Target -notmatch '^[a-f0-9]{40}$') { throw 'Нужен точный SHA' }
$Base = 'a254d75c51fbf7a3eb2210c8b59016cc414e66f1'
$Compose = @('--env-file', '.env', '-f', 'docker\compose\docker-compose.yml')
function G { & git @args; if ($LASTEXITCODE -ne 0) { throw 'Git command failed' } }
function D { & docker @args; if ($LASTEXITCODE -ne 0) { throw 'Docker command failed' } }
G status --short
if ((G branch --show-current) -ne 'main' -or (G rev-parse HEAD) -ne $Base) { throw 'STOP: другой baseline' }
G diff --exit-code
G diff --cached --exit-code
$Head = D exec eos-api alembic current
if (-not ($Head | Where-Object { $_ -match '^20261009_0078\b' })) { throw 'STOP: Alembic != 0078' }
G fetch origin main
if ((G rev-parse origin/main) -ne $Target) { throw 'STOP: remote SHA отличается' }
G merge-base --is-ancestor $Base $Target
G diff --name-only $Base $Target  # сверить ровно K5D package, без K5A/посторонних файлов
G merge --ff-only $Target
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach ($Service in @('api','automation-worker','frontend')) {
    $Image = D inspect --format '{{.Image}}' "eos-$Service"
    D image tag $Image "eos-k5d-rollback-${Service}:$Stamp"
}
D compose @Compose build api automation-worker frontend
D compose @Compose up -d --no-deps --no-build api automation-worker frontend
D compose @Compose ps api automation-worker frontend
D exec eos-api alembic current  # должен остаться 20261009_0078
D exec eos-api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=15).status); print(urllib.request.urlopen('http://127.0.0.1:8000/health/database', timeout=15).status)"
D exec eos-frontend node -e "fetch('http://127.0.0.1:5173').then(r=>{if(!r.ok)process.exit(1);console.log(r.status)}).catch(()=>process.exit(1))"
```

Health может потребовать повторения после запуска контейнеров. Worker — running;
его runtime status и ручной recipe execution проверить в EOS. HTTP 200 health
не заменяет business smoke.

Rollback: сохранены три старых image tags с `$Stamp`. Подставить их как `image`
для соответствующих services в отдельном временном Compose override и выполнить
`up -d --no-deps --no-build` только этих трёх services. PostgreSQL/volumes/schema
и сохранённую историю не откатывать; старый K5B API не отображает новые audit approvals.

## Smoke после deployment

- ADMIN/шеф/руководитель производства: три pilot cards, source/nested/prepared,
  единицы/Decimal/даты, русские статусы и история. INCOMPLETE не имеет confirm.
- SELLER и прочие исключённые роли: раздел отсутствует, прямые recipe GET/POST — 403.
- Один ручной refresh из карточки: Core progress → terminal result, без дубля
  execution; история сохранена, расписание и batch 141 не включены.
- Confirm только после независимой Office-сверки; автор/дата/версия видны,
  `ready_for_production=false`. Детали в [K5D review](STAGE_3_2_K5D_REPORT_2026-10-09.md).
