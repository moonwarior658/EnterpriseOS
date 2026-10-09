# K5B — Windows deployment и ограниченный live-пилот

09.10.2026, Asia/Yekaterinburg. **Подготовка, до deployment**.
Команды ниже выполняет оператор после отдельного разрешения на production update.
Этот документ не подтверждает deployment, live-пилот или iikoOffice acceptance.

## Что проверено и что ещё является deployment gate

Миграция 0078 имеет parent 0077. SQL содержит BEGIN/COMMIT, CREATE двух новых
таблиц, их constraints/index, CREATE trigger function и двух UPDATE/DELETE guards;
единственный UPDATE существующей таблицы — `alembic_version`.
Нет backfill, изменений product/Supply/price tables или регистрации расписаний.
В PostgreSQL 17.10 проверено сохранение fingerprints всех 92 существующих
таблиц (14 populated synthetic fixture tables) при `0077 → 0078 → 0077 → 0078`.
Новые таблицы пустые. Concurrent retry/immutability/filled downgrade guard и
manual worker проходят. Это **не** проверка реального production backup.

Live read-only preflight не выполнен: SSH аутентификация недоступна. Текущий
production HEAD/Alembic/DDL permissions/collisions/backup должны быть проверены
оператором. Старый K5A baseline: `a5a02823906ac467bceb8f98ad971377a5f31d6e`,
Alembic `20261009_0077`; не выдавать его за свежую проверку.
Обязательный rehearsal на восстановленной production-копии приведён ниже.

## Контрольные изделия — ровно 3 подтверждённых root

K5A evidence SHA-256: `92bd43e58cc51994580b160db1e770a2e02c5e171e3d7a5f58f764a220c47342`.
`key` — первые 16 hex SHA-256 UUID, не API UUID. Все три root имеют единицу «шт»;
разные единицы проверяются на ингредиентах, не выдуманным весовым root.

| K5A product key | Контроль | Исторические ориентиры K5A |
|---|---|---|
| `5fcc771dd5101343` | Вложенность, кг/шт, нулевая норма, store scope | COMMON; root chart `fedff96e2cb44f8a` с 28.08.2026; tree 9, prepared rows 17. PREPARED ingredient `7bed85eff66bab7c`: 0.15 / 0.15 / 0.1 кг на 1 шт. Другая DISH-строка: 1 шт при unitWeight 0.13 кг/шт. GOODS amountIn=0 не заменять amountIn1=1 |
| `b22356f1bc446f77` | Второй независимый nested root, общий полуфабрикат не считать циклом | COMMON; chart `f6bc1ba5e1cb4c91` с 01.12.2025; tree 6, prepared rows 14 |
| `47d5bdfb4b6f1aa7` | Смена версии и проблемная размерная рецептура | SPECIFIC + null size references/scales: ожидается INCOMPLETE с SIZE_REQUIRES_VERIFICATION. Chart `984eeddca4392a8e` до 01.06.2026 (exclusive), `240e551c518867b2` с 01.06; ingredient `7955e891d630a0d0` amountIn 0.03 → 0.05. Tree 5, prepared rows 13 на 09.10 |

Department K5A: `a8e0fe727d8767fd` — UUID, использованный в запросах departmentId.
Resolver ищет **точное соответствие hash** среди existing published EOS source
UUID и existing explicit OLAP department UUID. Он не подставляет corporation/group
ID или EOS Department ID и не сопоставляет по имени. При отсутствии/дубликате
ключа — STOP. Warehouse/size остаются null. Resolver должен вывести реальные UUID
в приватный файл перед пилотом; здесь они не восстановлены, так как доступа нет.

Ориентиры численности/версий — датированное наблюдение, не требование искусственно
вернуть старую норму на сегодняшнюю дату. Если источник изменился, сохранить новое
наблюдение, зафиксировать расхождение и сверить Office.

## A. Preflight, получение кода и сборка — PowerShell 7

Не запускать `scripts/backup-postgres.ps1`: его retention удаляет старые backups.
Ниже отдельный backup без удаления исторических файлов. Не использовать down -v,
reset, clean, volume prune, git force или Alembic downgrade заполненной истории.

```powershell
Set-Location C:\eos
$ErrorActionPreference = 'Stop'
$PSNativeCommandArgumentPassing = 'Standard'
$Compose = @('--env-file', '.env', '-f', 'docker\compose\docker-compose.yml')
$Target = Read-Host 'Полный K5B SHA из передачи'
if ($Target -notmatch '^[a-f0-9]{40}$') { throw 'Нужен точный SHA' }
$Base = 'a5a02823906ac467bceb8f98ad971377a5f31d6e'
function D { & docker @args; if ($LASTEXITCODE -ne 0) { throw 'Docker command failed' } }
function G { & git @args; if ($LASTEXITCODE -ne 0) { throw 'Git command failed' } }
G status --short
if ((G branch --show-current) -ne 'main') { throw 'STOP: branch != main' }
if ((G rev-parse HEAD) -ne $Base) { throw 'STOP: другой baseline, нужен новый review' }
G diff --exit-code
G diff --cached --exit-code
# Ранее untracked K5A: 2026-09-01, M, backup/, output/ и необычное compose-имя.
# Сверить фактический untracked список отдельно; ничего не удалять.
D exec eos-api alembic current  # оператор подтверждает ровно 20261009_0077
G fetch origin main
if ((G rev-parse origin/main) -ne $Target) { throw 'STOP: origin/main != переданный SHA' }
G merge-base --is-ancestor $Base $Target
G diff --name-only $Base $Target  # только разрешённые K5B paths из release report
G merge --ff-only $Target
if ((G rev-parse HEAD) -ne $Target) { throw 'SHA mismatch' }
$OldApiImage = D inspect --format '{{.Image}}' eos-api
$OldWorkerImage = D inspect --format '{{.Image}}' eos-automation-worker
$ApiImageTag = D inspect --format '{{.Config.Image}}' eos-api
$WorkerImageTag = D inspect --format '{{.Config.Image}}' eos-automation-worker
D compose @Compose build api automation-worker
# Только build: ещё не обновляет контейнеры и не мигрирует DB.
$PilotSource = Get-Content -Raw -Encoding UTF8 scripts\k5b_pilot.py
$PilotSource | docker exec -i eos-api python - preflight
if ($LASTEXITCODE -ne 0) { throw 'STOP: 0077, collision or read-only preflight failed' }
```

Не продолжать при неизвестном HEAD/head, tracked changes, target-path collision
с untracked файлом, нескольких Alembic heads или конфликте recipe table/function.
Preflight helper использует SET TRANSACTION READ ONLY, не обращается к iiko.
Он проверяет CREATE schema, USAGE plpgsql и REFERENCES target tables; прав не выдаёт.
Сборка/PowerShell команды проверены по Compose/Dockerfile, на Windows не выполнялись.

## B. Quiesce → verified backup → rehearsal на копии

Плановое окно: остановятся API и automation worker; PostgreSQL и остальные
сервисы остаются. Если любой шаг не проходит, **не выполнять production migration**.

```powershell
D compose @Compose stop api automation-worker
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$RunDir = Join-Path 'C:\eos\backup' "k5b-$Stamp"
New-Item -ItemType Directory -Path $RunDir | Out-Null
$DumpInContainer = "/tmp/eos_k5b_$Stamp.dump"
$Dump = Join-Path $RunDir 'eos-before-0078.dump'
# script передаётся на stdin sh; значения credentials не выводятся.
$DumpCommand = 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --file=' + $DumpInContainer
$DumpCommand | docker exec -i eos-postgres sh
if ($LASTEXITCODE -ne 0) { throw 'Backup failed' }
D exec eos-postgres pg_restore --list $DumpInContainer | Out-File -Encoding utf8 (Join-Path $RunDir 'dump-toc.txt')
D cp "eos-postgres:$DumpInContainer" $Dump
if ((Get-Item $Dump).Length -le 0) { throw 'Empty backup' }
Get-FileHash $Dump -Algorithm SHA256 | Format-List | Out-File -Encoding utf8 (Join-Path $RunDir 'dump-sha256.txt')
# Сохранить исходные images для rollback, без secrets.
@{api=$OldApiImage; worker=$OldWorkerImage; api_tag=$ApiImageTag; worker_tag=$WorkerImageTag; target=$Target; base=$Base} |
    ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $RunDir 'images.json')
$RestoreContainer = "eos-k5b-restore-$Stamp"
D run -d --name $RestoreContainer --network enterpriseos-network -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17-alpine
$Ready = $false
for ($i=0; $i -lt 30; $i++) {
    docker exec $RestoreContainer pg_isready -U postgres *> $null
    if ($LASTEXITCODE -eq 0) { $Ready=$true; break }
    Start-Sleep -Seconds 1
}
if (-not $Ready) { throw 'Restore PostgreSQL not ready' }
D cp $Dump "${RestoreContainer}:/tmp/backup.dump"
D exec $RestoreContainer pg_restore --list /tmp/backup.dump | Out-File -Encoding utf8 (Join-Path $RunDir 'restore-toc.txt')
D exec $RestoreContainer pg_restore -U postgres -d postgres --no-owner --no-acl --exit-on-error /tmp/backup.dump
$FixtureDb = @('-e', "POSTGRES_HOST=$RestoreContainer", '-e', 'POSTGRES_PORT=5432', '-e', 'POSTGRES_DB=postgres', '-e', 'POSTGRES_USER=postgres', '-e', 'POSTGRES_PASSWORD=fixture')
# Проверить restored head/collisions и fingerprints до изменения.
$PilotSource | docker compose @Compose run --rm --no-deps -T @FixtureDb api python - preflight |
    Set-Content -Encoding utf8 (Join-Path $RunDir 'restored-before.json')
if ($LASTEXITCODE -ne 0) { throw 'Restored preflight failed' }
D compose @Compose run --rm --no-deps @FixtureDb api alembic upgrade 20261009_0078
D compose @Compose run --rm --no-deps @FixtureDb api alembic current
# В restored DB проверка fingerprints возможна через resolve; требует точных K5A UUID.
$PilotSource | docker compose @Compose run --rm --no-deps -T @FixtureDb api python - resolve |
    Set-Content -Encoding utf8 (Join-Path $RunDir 'restored-after.json')
if ($LASTEXITCODE -ne 0) { throw 'Restored identity/fingerprint check failed' }
$Before = Get-Content -Raw (Join-Path $RunDir 'restored-before.json') | ConvertFrom-Json
$After = Get-Content -Raw (Join-Path $RunDir 'restored-after.json') | ConvertFrom-Json
if (($Before.protected | ConvertTo-Json -Depth 10 -Compress) -ne ($After.protected | ConvertTo-Json -Depth 10 -Compress)) { throw 'Protected data changed on restored rehearsal' }
# Тестовая копия целиком disposable: удалить только её контейнер и его temporary volume.
D rm -f -v $RestoreContainer
# Сохранять verified host backup; контейнерный временный файл можно убрать после копии.
D exec eos-postgres rm $DumpInContainer
```

Restore без owner/ACL проверяет восстанавливаемость данных/schema; recovery исходной
DB требует original roles/permissions и отдельного решения. Rehearsal использует
только восстановленную копию; worker на ней не запускается и iiko не вызывается.
Если resolver не подтвердил три точных UUID, STOP, не выбирать похожие имена.

## C. Production migration и только API/worker

Выполняется только после успешного B и решения оператора продолжать deployment.

```powershell
# libpq bounds: при ожидании FK locks миграция откатится, вместо бесконечного зависания.
D compose @Compose run --rm --no-deps -e 'PGOPTIONS=-c lock_timeout=5000 -c statement_timeout=120000' api alembic upgrade 20261009_0078
D compose @Compose run --rm --no-deps api alembic current  # ровно 0078
D compose @Compose up -d --no-deps --no-build api automation-worker
D compose @Compose ps api automation-worker postgres
D exec eos-api python -c "import urllib.request; assert urllib.request.urlopen('http://127.0.0.1:8000/health/database',timeout=10).status == 200"
D exec eos-api python -c "from app.automation.local_actions import LocalAutomationActionExecutor as E; assert E.supports('products.sync_iiko_recipes')"
```

Проверить API/login/products/K4 photos через existing UI и статус worker heartbeat
через существующую диагностику. Не выводить .env, полный compose config или raw
logs с credentials/payload. Frontend/n8n/PostgreSQL не пересобирать/не обновлять.
Не запускать пилот до подтверждения smoke и отсутствия recipe schedules.

Если deployment не прошёл: остановить API/worker, восстановить **предыдущие image
tags**, поднять предыдущие images без build; schema 0078 и recipe history оставить.
Никакого автоматического downgrade или восстановления поверх действующей DB.
До завершения deployment/pilot не выполнять image prune.

```powershell
D compose @Compose stop api automation-worker
D image tag $OldApiImage $ApiImageTag
D image tag $OldWorkerImage $WorkerImageTag
D compose @Compose up -d --no-deps --no-build api automation-worker
```

## D. Live-пилот после deployment — четыре ручных execution, всегда 3 root

Получить реальный ID действующего Human TECHNICAL_ADMIN из существующей user/
employee конфигурации; не угадывать `actor=1`, не использовать SERVICE account.
Operator helper вызывает тот же service enqueue/authorization/audit/outbox,
который использует POST `/products/recipes/refresh`. Credentials iiko остаются в
existing settings и не попадают в evidence. Export — приватный технологический
artifact с UUID/рецептурами, не файл для публикации в Git.

```powershell
$PilotSource | docker exec -i eos-api python - resolve |
    Set-Content -Encoding utf8 (Join-Path $RunDir 'pilot-identities.json')
if ($LASTEXITCODE -ne 0) { throw 'Identity resolution failed' }
$Actor = Read-Host 'Подтверждённый Human TECHNICAL_ADMIN user ID'
if ($Actor -notmatch '^[1-9][0-9]*$') { throw 'Нужен подтверждённый user ID' }
# Исполнять по очереди. Не ставить следующий run до terminal status текущего.
$PilotSource | docker exec -i eos-api python - enqueue --actor $Actor --date 2026-10-09 |
    Set-Content -Encoding utf8 (Join-Path $RunDir 'run-1-request.json')
if ($LASTEXITCODE -ne 0) { throw 'Enqueue failed' }
$Execution = (Get-Content -Raw (Join-Path $RunDir 'run-1-request.json') | ConvertFrom-Json).execution_id
$PilotSource | docker exec -i eos-api python - export --execution $Execution |
    Set-Content -Encoding utf8 (Join-Path $RunDir 'run-1.json')
if ($LASTEXITCODE -ne 0) { throw 'Export failed' }
# Повторять ТОЛЬКО export до succeeded; failed/timed_out/cancelled — STOP и review.
```

После terminal success run-1 использовать следующие команды **по одному блоку**.
Функция не опрашивает автоматически и не запускает полный batch.

```powershell
function Request-Pilot([string]$Name, [string]$Date) {
    $PilotSource | docker exec -i eos-api python - enqueue --actor $Actor --date $Date |
        Set-Content -Encoding utf8 (Join-Path $RunDir "$Name-request.json")
    if ($LASTEXITCODE -ne 0) { throw 'Enqueue failed' }
}
function Export-Pilot([string]$Name) {
    $Id = (Get-Content -Raw (Join-Path $RunDir "$Name-request.json") | ConvertFrom-Json).execution_id
    $PilotSource | docker exec -i eos-api python - export --execution $Id |
        Set-Content -Encoding utf8 (Join-Path $RunDir "$Name.json")
    if ($LASTEXITCODE -ne 0) { throw 'Export failed' }
    $Status = (Get-Content -Raw (Join-Path $RunDir "$Name.json") | ConvertFrom-Json).status
    Write-Host "$Name $Status"  # next Request только после succeeded
}
Request-Pilot 'run-2' '2026-10-09'
Export-Pilot 'run-2'  # повторять только Export-Pilot до terminal status
# После succeeded run-2:
Request-Pilot 'run-boundary-before' '2026-05-31'
Export-Pilot 'run-boundary-before'
# После succeeded run-boundary-before:
Request-Pilot 'run-boundary-after' '2026-06-01'
Export-Pilot 'run-boundary-after'
```

Вторая постановка имеет точно тот же payload и дату, но новое execution.
Не повторять enqueue для polling. Исторические runs содержат те же три root.
Если пилот выполняется позже 09.10, эти запросы остаются историческими: сегодняшний
context требует отдельно выбранной явной даты, без автоматического rolling date.
Ни один запуск не содержит `pilot_observation_id`; расширение >5 запрещено планом.

```powershell
D cp (Join-Path $RunDir 'run-1.json') eos-api:/tmp/k5b-first.json
D cp (Join-Path $RunDir 'run-2.json') eos-api:/tmp/k5b-second.json
$PilotSource | docker exec -i eos-api python - compare --first /tmp/k5b-first.json --second /tmp/k5b-second.json |
    Set-Content -Encoding utf8 (Join-Path $RunDir 'repeat-check.json')
if ($LASTEXITCODE -ne 0) { throw 'Repeat comparison failed' }
$Baseline = Get-Content -Raw (Join-Path $RunDir 'pilot-identities.json') | ConvertFrom-Json
$RunOne = Get-Content -Raw (Join-Path $RunDir 'run-1.json') | ConvertFrom-Json
if (($Baseline.protected | ConvertTo-Json -Depth 10 -Compress) -ne ($RunOne.protected | ConvertTo-Json -Depth 10 -Compress)) { throw 'STOP: protected data differs from pre-pilot baseline; inspect independent business traffic' }
$Repeat = Get-Content -Raw (Join-Path $RunDir 'repeat-check.json') | ConvertFrom-Json
if (-not $Repeat.passed) { throw 'STOP: repeat/context/versions/protected fingerprints changed; investigate source or concurrent activity' }
D exec eos-api rm /tmp/k5b-first.json /tmp/k5b-second.json
```

Repeat создаёт новое execution/observation, но при unchanged source/context использует
те же content versions и manifest; повторная доставка **того же execution_id**
не должна создать observation второй раз (проверено локально/PG, не провоцировать
повторную доставку ручным SQL в production). При реальном изменении источника
versions могут отличаться: сохранить evidence и сверить Office; не «исправлять»
историю. Protected fingerprints могут измениться из-за штатного K3/бизнес-трафика;
это повод раздельной проверки причин, не доказательство нарушения K5B.

## Приёмка и независимая сверка Office

Техническая приёмка требует:

1. Head 0078, API/worker smoke, verified backup/rehearsal artifacts, нет K5B schedule.
2. Все 4 execution terminal, для каждого ровно 3 observations одного tenant/source/
   department/date; только три подтверждённых source UUID. Существующие catalog,
   price, photos и Supply не изменены K5B; новые root/ingredients не импортированы.
3. SOURCE chart UUID/date/norms/text и PREPARED сохранены отдельно, Decimal exact;
   manifest перечисляет nested chart UUID/hash + units/packages/scales + scope.
4. На 31.05/01.06 третье изделие выбирает ожидаемые разные UUID карты и норму
   ingredient `7955…` 0.03/0.05, без изменения старой observation.
5. SPECIFIC/null sizes остаётся INCOMPLETE; missing/conflict не получает READY.
   Все ready_for_production=false. COMMON может быть UNCONFIRMED либо иным
   объяснённым статусом, если source изменился/обнаружен новый quality issue.
6. Repeat report подтверждает новые observation IDs и reuse unchanged versions.
   Исходный snapshot сохраняется при любом последующем неполном ответе.

**Независимо:** шеф/технолог открывает те же source product/chart UUID в iikoOffice,
тот же department/store/date/size и сверяет root, каждый непосредственный и nested
ingredient, mainUnit, assembledAmount, amountIn/Middle/Out, dates, технологические
тексты, DIRECT/ASSEMBLE, inverse store filters, размеры и prepared/writeoff смысл.
Не считать ещё один iiko API ответ независимой проверкой. Для проблемной карты
зафиксировать реальное отсутствие размеров и объяснение специалиста без автоправки.

В приватном протоколе Office: проверяющий, дата/версия Office, UUID/root/chart,
department/store/size (unknown остаётся unknown), effective date, снимок/export
Office, строковая таблица expected/actual Decimal + unit, verdict и перечень
расхождений. Отдельно сверить обе исторические даты и подтвердить version transition.
Пилот принимается человеком только после технического отчёта и этой сверки.
K5C monetary cost, полный rollout 141, расписание и Gate K этим не разрешаются.
