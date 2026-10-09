# K2 production runbook — миграция 0075 и API/frontend

**09.10.2026.** Техническая реализация принята владельцем к релизной проверке.
Команды для оператора, PowerShell в `C:\eos`; Codex deployment не выполняет.
Release SHA берётся из сообщения о push. Выполнять блоки последовательно,
останавливаться при любой ошибке. Не запускать bootstrap/publish/collect, не
перезагружать 141 запись K1 и не включать новые расписания.

## 1. Preflight и точный release

```powershell
Set-Location C:\eos
$dc = @('--env-file', '.\.env', '-f', '.\docker\compose\docker-compose.yml')
$releaseSha = 'ВСТАВИТЬ_SHA_ИЗ_ОТЧЁТА_О_PUSH'
git status --short
if ((git branch --show-current) -ne 'main') { throw 'Нужна main' }
git diff --quiet
if ($LASTEXITCODE -ne 0) { throw 'Есть локальные tracked изменения' }
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) { throw 'Есть staged изменения' }
$previousSha = git rev-parse HEAD
git fetch origin main
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed' }
if ((git rev-parse origin/main) -ne $releaseSha) { throw 'origin/main не равен согласованному release SHA' }
docker compose @dc exec -T api alembic current
if ($LASTEXITCODE -ne 0) { throw 'Не удалось проверить Alembic' }
```

Ожидаемый Alembic — **20261008_0074**. При другом head остановиться. Существующие
untracked backups/production files сохраняются, не добавляются в git.

## 2. Backup и снимок исходной партии

Подтвердить recovery path/проверенную процедуру восстановления перед migration.
Backup создаётся в PostgreSQL-контейнере и копируется как файл: PowerShell не
перенаправляет бинарный dump через stdout.

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path (Get-Location) "backup\k2-$stamp"
New-Item -ItemType Directory -Path $backupDir -ErrorAction Stop | Out-Null
$previousSha | Set-Content (Join-Path $backupDir 'previous-sha.txt')
docker inspect --format '{{.Image}}' eos-api eos-frontend | Set-Content (Join-Path $backupDir 'previous-images.txt')
$dumpInContainer = "/tmp/eos-k2-$stamp.dump"
docker compose @dc exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f "$1"' sh $dumpInContainer
if ($LASTEXITCODE -ne 0) { throw 'Backup failed' }
docker compose @dc exec -T postgres pg_restore --list $dumpInContainer | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Backup TOC invalid' }
docker cp "eos-postgres:$dumpInContainer" (Join-Path $backupDir 'database.dump')
if ($LASTEXITCODE -ne 0) { throw 'Backup copy failed' }
Get-FileHash (Join-Path $backupDir 'database.dump') -Algorithm SHA256

function Invoke-K2Sql([string]$sql) {
    $result = $sql | docker compose @dc exec -T postgres sh -c 'psql -X -A -t -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
    if ($LASTEXITCODE -ne 0) { throw 'SQL check failed' }
    return ($result -join "`n").Trim()
}
Invoke-K2Sql "SELECT b.id,b.tenant_id,b.source_id,count(p.id) FROM product_knowledge_batches b LEFT JOIN product_knowledge_products p ON p.batch_id=b.id AND p.tenant_id=b.tenant_id WHERE b.rolled_back_at IS NULL AND b.report->>'kind' IS DISTINCT FROM 'MANUAL_UUID_CONFIRMATION' GROUP BY b.id,b.tenant_id,b.source_id;"
$k1Batch = 'ВСТАВИТЬ_UUID_ИСХОДНОЙ_ПАРТИИ_ИЗ_СПИСКА'
$k1Batch = ([guid]$k1Batch).ToString()
$k1Sql = @"
WITH batch AS (SELECT * FROM product_knowledge_batches WHERE id='$k1Batch'::uuid),
products AS (SELECT p.* FROM product_knowledge_products p JOIN batch b ON p.batch_id=b.id AND p.tenant_id=b.tenant_id)
SELECT jsonb_build_object(
 'batch_count',(SELECT count(*) FROM batch WHERE rolled_back_at IS NULL),
 'product_count',(SELECT count(*) FROM products),
 'published_count',(SELECT count(*) FROM products WHERE published),
 'batches_hash',(SELECT md5(jsonb_agg(to_jsonb(b) ORDER BY b.id)::text) FROM batch b),
 'products_hash',(SELECT md5(jsonb_agg(to_jsonb(p)-ARRAY['local_name','local_description','characteristics','composition','allergens','storage','training','version','deleted_at','verified_at','verified_by_employee_id','verified_by_name'] ORDER BY p.id)::text) FROM products p),
 'prices_hash',(SELECT md5(coalesce(jsonb_agg(to_jsonb(pr) ORDER BY pr.id),'[]'::jsonb)::text) FROM product_knowledge_prices pr JOIN products p ON pr.product_id=p.id AND pr.tenant_id=p.tenant_id));
"@
$beforeK1 = Invoke-K2Sql $k1Sql
$k1 = $beforeK1 | ConvertFrom-Json
if ($k1.batch_count -ne 1 -or $k1.product_count -ne 141 -or $k1.published_count -ne 141) { throw 'K1 baseline не подтверждён' }
$beforeK1 | Set-Content (Join-Path $backupDir 'k1-before.json')
```

Хеши покрывают исходные поля изделий (включая EOS ID/iiko UUID/source/batch/связи/
статус/публикацию), всю запись batch с manifest и все её цены. Новые поля 0075
исключены из сравнения. До завершения сравнения не выполнять действия K2.

## 3. Обновление

```powershell
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { throw 'Pull failed' }
if ((git rev-parse HEAD) -ne $releaseSha) { throw 'Неверный release SHA' }
docker compose @dc build api frontend
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
docker compose @dc run --rm --no-deps api alembic upgrade 20261009_0075
if ($LASTEXITCODE -ne 0) { throw 'Migration failed: не запускать новый API' }
$afterK1 = Invoke-K2Sql $k1Sql
$afterK1 | Set-Content (Join-Path $backupDir 'k1-after.json')
if ($afterK1 -ne $beforeK1) { throw 'K1 изменился: остановить rollout и исследовать' }
docker compose @dc up -d --no-deps api frontend
if ($LASTEXITCODE -ne 0) { throw 'Service update failed' }
docker compose @dc exec -T api alembic current
if ($LASTEXITCODE -ne 0) { throw 'Alembic check failed' }
docker compose @dc exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').status); print(urllib.request.urlopen('http://127.0.0.1:8000/health/database').status)"
if ($LASTEXITCODE -ne 0) { throw 'API health failed' }
docker compose @dc ps api frontend
```

Ожидаются head **0075**, оба health **200**, работающие API/frontend.
Пересобираются/обновляются только эти два сервиса. PostgreSQL, automation-worker,
n8n, proxy и volumes не пересоздаются; K2 не меняет worker/outbox/jobs.
Существующий frontend Dockerfile запускает Vite dev server — этот релиз не меняет
способ hosting; локальный production build проверен отдельно.

## 4. Release smoke и rollback

- До пользовательских edits: `/products` показывает 141 изделие; повторное
  сравнение `$k1Sql` совпадает с baseline. Проверить Sales/Statistics и Supply.
- Управляют **ADMIN, NETWORK_MANAGER, CHEF_CONFECTIONER, HEAD_OF_PRODUCTION**;
  **DIRECTOR, DEPUTY_DIRECTOR** только читают. Все остальные роли — 403, включая
  прямые write/history/candidate API calls. Guards сотрудника/производства сохраняются.
- На согласованном изделии: edit → verify → edit (проверка снялась), status →
  delete → deleted filter → restore/re-add того же UUID; EOS ID/история/связи
  сохранены. Проверить progress, историю, конфликт двух окон 409, keyboard/error/loading.
  Добавление нового изделия — только с отдельным подтверждением конкретного UUID.
- При сбое остановить выпуск новых действий K2, сохранить schema/local data/audit.
  После K2 записей downgrade 0075 запрещён. Старый API игнорирует deleted_at и
  новую матрицу: возврат старых images допустим только с закрытым разделом и
  backend маршрутом `/products` до совместимого исправления. Не выполнять
  автоматическое восстановление backup поверх новых изменений. Решение об откате
  — отдельная согласованная операция по сохранённым previous SHA/image IDs.

Production smoke/backup/rollout в рамках подготовки этого документа не выполнялись.
