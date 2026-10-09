# K3: обычные цены — production runbook (09.10.2026)

Релиз принят владельцем для обычного прейскуранта RUB без категории. Полный
Gate K3 открыт: неизвестные SCHEDULED-приоритеты скрывают сумму и требуют
проверки. Deployment выполняет оператор; Codex production не обновлял.

Команды ниже — PowerShell в `C:\eos`. Выполнять по шагам, после каждой native
команды проверять `$LASTEXITCODE`; при ненулевом значении остановиться.
Не очищать существующие untracked files. API/worker требуют 0076; старый API
совместим с добавленной таблицей, новый frontend совместим со старым API.
Расписание цен до завершения проверки должно оставаться выключенным.

## 1. Preflight и backup

```powershell
Set-Location C:\eos
$Compose = 'docker\compose\docker-compose.yml'
$ReleaseSha = Read-Host 'SHA релиза из отчёта Codex'
git status --short
git diff --exit-code
git diff --cached --exit-code
git fetch origin main
if ((git rev-parse origin/main).Trim() -ne $ReleaseSha) { throw 'main изменился: повторить review' }
docker exec eos-api alembic current
# Ожидается 20261009_0075; другой head требует отдельного review.
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
New-Item -ItemType Directory -Force backup | Out-Null
$Dump = "eos-k3-$Stamp.dump"
docker exec eos-postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/eos-k3.dump'
docker exec eos-postgres sh -c 'pg_restore --list /tmp/eos-k3.dump >/tmp/eos-k3.list'
docker cp eos-postgres:/tmp/eos-k3.dump "backup\$Dump"
Get-Item "backup\$Dump"
Get-FileHash "backup\$Dump" -Algorithm SHA256
```

Скопировать dump вне сервера. До миграции проверить восстановление этой копии
на изолированном PostgreSQL 17 (не на production), например:

```powershell
# Только на отдельном тестовом сервере; eos_k3_restore — новая одноразовая БД.
createdb -h 127.0.0.1 -U postgres eos_k3_restore
pg_restore -h 127.0.0.1 -U postgres -d eos_k3_restore --exit-on-error --no-owner "backup\$Dump"
```

## 2. Миграция и совместимое обновление

```powershell
git pull --ff-only origin main
if ((git rev-parse HEAD).Trim() -ne $ReleaseSha) { throw 'Неверный SHA' }
docker compose -f $Compose build api automation-worker frontend
docker compose -f $Compose run --rm --no-deps api alembic upgrade 20261009_0076
docker compose -f $Compose run --rm --no-deps api alembic current
docker compose -f $Compose up -d --no-deps api automation-worker frontend
docker compose -f $Compose ps api automation-worker frontend
```

Проверить вход, каталог/карточку, доступ продавца только к своей точке, ручные
правки/статусы/отметки управляющего. До публикации допустим индикатор отсутствия
снимка. Не запускать общий iiko reference sync. Не обновлять PostgreSQL/n8n.

## 3. Preview и публикация принятого снимка

`output/stage3_2_k3` содержит внутренние production price payloads и сохранён
только локально на Mac; в GitHub эти файлы не публикуются. До команд ниже
оператор передаёт их напрямую на сервер (из корня локального checkout):

```bash
ssh Leonid@212.220.15.55 'if not exist C:\eos\output mkdir C:\eos\output'
scp -r output/stage3_2_k3 'Leonid@212.220.15.55:C:/eos/output/'
```

Затем продолжить в PowerShell `C:\eos`; проверить manifest до публикации.

```powershell
$ActorId = [int](Read-Host 'ID действующего ADMIN этой компании')
$Tenant = 'eclair'
$Policy = Get-Content output\stage3_2_k3\policy.json -Raw | ConvertFrom-Json
$Source = $Policy.source_id
$Manifest = Get-Content output\stage3_2_k3\manifest.json -Raw | ConvertFrom-Json
foreach ($Entry in $Manifest.PSObject.Properties) {
  $Actual = (Get-FileHash "output\stage3_2_k3\$($Entry.Name)" -Algorithm SHA256).Hash.ToLower()
  if ($Actual -ne $Entry.Value) { throw "Артефакт изменён: $($Entry.Name)" }
}
docker cp output\stage3_2_k3\source_snapshot.json eos-api:/tmp/k3-source.json
docker exec eos-api python -m app.product_knowledge.cli prices-source-preview --tenant $Tenant --source $Source --actor-id $ActorId --snapshot /tmp/k3-source.json --report /tmp/k3-preview.json
docker cp eos-api:/tmp/k3-preview.json backup\k3-preview.json
$Preview = Get-Content backup\k3-preview.json -Raw | ConvertFrom-Json
$Hash = '4a55e7609971d085482e87b48a9b2110e69f174ccbb58acc6d1fa29ca908952d'
if ($Preview.plan_hash -ne $Hash) { throw 'Scope/hash изменился: recollect и новый review, не публиковать' }
docker exec eos-api python -m app.product_knowledge.cli prices-source-publish --tenant $Tenant --source $Source --actor-id $ActorId --snapshot /tmp/k3-source.json --expected-hash $Hash
```

Снимок получен 09.10.2026 в 11:11:08 Екатеринбург; публикация не меняет эту дату.
Если релиз отложен, снимок будет помечен устаревшим. Для нового сбора:

```powershell
docker cp output\stage3_2_k3\policy.json eos-api:/tmp/k3-policy.json
docker exec eos-api python -m app.product_knowledge.cli prices-collect --tenant $Tenant --source $Source --actor-id $ActorId --report /tmp/k3-policy.json --snapshot /tmp/k3-fresh.json
docker exec eos-api python -m app.product_knowledge.cli prices-source-preview --tenant $Tenant --source $Source --actor-id $ActorId --snapshot /tmp/k3-fresh.json --report /tmp/k3-fresh-preview.json
docker cp eos-api:/tmp/k3-fresh.json backup\k3-fresh.json
docker cp eos-api:/tmp/k3-fresh-preview.json backup\k3-fresh-preview.json
```

Новый hash сверить с новым содержимым и контрольными изделиями; не подставлять
его автоматически вместо принятого hash. При изменении ассортимента/mappings
preview остановится, требуется актуальный сбор. Публикация идемпотентна.

## 4. Проверка и включение hourly schedule

На 09.10.2026 сверить таблицу и карточку:
00667 — 150 RUB/порц (Матросова 15), 120 (Матросова 35, Игарская 25В);
01016 — 350 RUB/кг; 74615 — 2500 RUB/кг, обе позиции во всех трёх точках.
Missing/excluded — без суммы, без нуля/defaultSalePrice. Проверить время
получения и индикатор старше двух часов; ошибка обновления сохраняет дату и
последние успешные данные. Снять показатели статусов/проверки до и после.

После проверки использовать токен ADMIN текущей сессии (не сохранять в файлы
и не выводить). Указать HTTPS адрес портала без завершающего `/`:

```powershell
$ApiBase = Read-Host 'HTTPS адрес портала'
$Secret = Read-Host 'Токен ADMIN текущей сессии' -AsSecureString
$Token = [System.Net.NetworkCredential]::new('', $Secret).Password
$Headers = @{ Authorization = "Bearer $Token" }
$Schedules = Invoke-RestMethod -Uri "$ApiBase/api/automation/schedules" -Headers $Headers
# Убедиться, что для source нет второго products.sync_iiko_prices.
$Existing = @($Schedules | Where-Object { $_.automation_type -eq 'products.sync_iiko_prices' -and $_.payload.source_id -eq $Source })
if ($Existing.Count -ne 0) { throw 'Расписание уже существует: проверить его, не создавать дубль' }
$Body = @{ name='Обновление цен продукции'; automation_type='products.sync_iiko_prices'; scope_type='company'; scope_id=$null; schedule_config=@{type='interval';minutes=60}; payload=$Policy; recipients=@(); timezone='Asia/Yekaterinburg'; is_enabled=$false } | ConvertTo-Json -Depth 10
$Schedule = Invoke-RestMethod -Method Post -Uri "$ApiBase/api/automation/schedules" -Headers $Headers -ContentType 'application/json' -Body $Body
# Визуально сверить три UUID из policy, source, RUB и interval=60 в созданном расписании.
Invoke-RestMethod -Method Patch -Uri "$ApiBase/api/automation/schedules/$($Schedule.id)" -Headers $Headers -ContentType 'application/json' -Body '{"is_enabled":true}' | Select-Object id,is_enabled,next_run_at
Remove-Variable Token,Secret,Headers
```

После первого scheduled run проверить успех в «Регламентных задачах», новое
время успешного снимка в продукции, контрольные цены и сохранность EOS-полей.
При ошибке выключить расписание через тот же PATCH `{"is_enabled":false}`.
Не закрывать Gate K3 этим релизом.

## Откат

Остановить/выключить только расписание цен; вернуть API/worker/frontend к
предыдущему согласованному SHA с rebuild/up, оставив таблицу 0076. После
публикации downgrade 0076 намеренно запрещён для сохранения истории.
Восстановление production из backup — отдельное решение владельца; этот
runbook не разрешает удаление БД или истории.
