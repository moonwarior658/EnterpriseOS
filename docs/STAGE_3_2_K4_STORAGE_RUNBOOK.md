# K4 — хранение, резервное копирование и восстановление фотографий

09.10.2026. Инструкция для будущего согласованного production release; команды
в этом задании на production не выполнялись. K0–K3 работают на production по
подтверждению владельца; K4 пока локально на review.

## Хранение и пределы

EOS использует тот же механизм, что другие вложения: приватный filesystem и
защищённый API, без публичного static mount и внешнего object storage.
Compose подключает named volume `product_photo_uploads` только к API по пути
`/app/uploads/product-photos`; default `PRODUCT_PHOTO_UPLOAD_DIR` совпадает с ним.
Если путь переопределён, mount должен совпадать с фактическим путём.
Worker не управляет фотографиями и не нуждается в этом volume.

Файл: `<EOS product UUID>/<SHA-256 нормализованного содержимого>.webp`.
Имя и расширение загрузки, название изделия, tenant и remote URL не становятся
путём файла. В БД хранится `local_photo_hash`, в append-only audit — before/after,
причина, сотрудник, роль и время. JPEG/PNG/WebP до 10 MiB, не более 16 млн пикселей,
один кадр; actual format и декодирование обязательны. WebP ограничивается 1600×1600,
EXIF и прочие исходные метаданные не передаются в сохранение.

Blob записывается атомарно до commit. При DB/audit failure указатель откатывается;
может остаться неиспользуемый blob. Файлы предыдущих версий и такие blobs сейчас
сохраняются без автоматического удаления. Размер volume и свободное место нужно
контролировать; автоматическая retention/очистка не утверждена. Ошибка записи
возвращает безопасный 503, частичный файл не публикуется. Удаление фотографии
снимает только указатель; удаление самого изделия не удаляет фотографию.

## Согласованный backup

Нужны **вместе** PostgreSQL dump (включая audit) и весь photo volume.
До первой production миграции требуется проверенный backup и recovery rehearsal.
DB dump без файлов не позволяет восстановить фото и историю содержимого.
Остановить API и worker на время согласованного snapshot; PostgreSQL остаётся
запущенным. Не запускать автоматическую очистку файлов. Пример PowerShell из
`C:\eos`; директорию backup выбирать вне checkout и хранить с ограниченным доступом:

```powershell
$compose = 'docker\compose\docker-compose.yml'
$backupDir = 'C:\eos-backups\K4-YYYYMMDD-HHMM'
New-Item -ItemType Directory -Force $backupDir | Out-Null
# Проверить, что фактический mount имеет нужный Destination и Type=volume.
(docker inspect eos-api | ConvertFrom-Json).Mounts |
  Where-Object Destination -eq '/app/uploads/product-photos'
docker compose -f $compose stop api automation-worker
# -f внутри контейнера и docker cp сохраняют binary dump без PowerShell redirection.
docker exec eos-postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/k4-eos.dump'
if ($LASTEXITCODE -ne 0) { throw 'pg_dump failed' }
docker exec eos-postgres pg_restore --list /tmp/k4-eos.dump
if ($LASTEXITCODE -ne 0) { throw 'dump validation failed' }
docker cp eos-postgres:/tmp/k4-eos.dump (Join-Path $backupDir 'eos.dump')
if ($LASTEXITCODE -ne 0) { throw 'dump copy failed' }
docker run --rm --volumes-from eos-api:ro -v "${backupDir}:/backup" alpine:3.22 tar -C /app/uploads/product-photos -czf /backup/product-photos.tar.gz .
if ($LASTEXITCODE -ne 0) { throw 'media backup failed' }
docker run --rm -v "${backupDir}:/backup:ro" alpine:3.22 tar -tzf /backup/product-photos.tar.gz
if ($LASTEXITCODE -ne 0) { throw 'media archive validation failed' }
Get-FileHash (Join-Path $backupDir 'eos.dump'), (Join-Path $backupDir 'product-photos.tar.gz') |
  Export-Csv -NoTypeInformation (Join-Path $backupDir 'checksums.csv')
# Запускать сервисы после проверки комплекта; при сбое сначала исправить backup.
docker compose -f $compose start api automation-worker
```

Для первого релиза volume ещё может отсутствовать: сохранить текущий DB backup,
создать/подключить volume через согласованный release, затем проверить mount и
сделать первый согласованный комплект после пилотной загрузки.
Записать Git SHA, Alembic head, compose project, image IDs, время и checksum
комплекта. `pg_restore --list` и tar listing проверяют читаемость, но не заменяют
фактическую репетицию восстановления. После переноса проверить checksum повторно.
Не удалять контейнеры/volumes production и не использовать `down -v`.

## Recovery rehearsal и приёмка release

1. В отдельном изолированном окружении восстановить dump в **новую пустую** БД
   через `pg_restore --exit-on-error`; восстановить tar в **новый пустой** photo
   volume. Использовать совместимый backend, не downgrade populated schema.
2. Подключить восстановленные DB и volume к тестовому API; проверить путь/mount.
   Выполнить `python -m app.product_knowledge.media` внутри тестового API.
   Проверка проходит при `missing=0`, `damaged=0`, exit code 0. Она проверяет SHA-256
   каждого current/audit reference; не печатает названия, файлы или credentials.
3. Войти разрешённым пользователем и проверить карточку/таблицу/mobile фото,
   заглушку без фото, историю причины/сотрудника, просмотр DIRECTOR и запрет SELLER.
4. Загрузить фото, заменить и удалить с причиной; повторить запрос и проверить
   отсутствие дублей аудита. Конкурентная правка старой версии должна дать 409.
5. После загрузки выполнить `docker compose -f docker/compose/docker-compose.yml restart api`
   **в тестовом окружении**, затем `up -d --force-recreate --no-deps api` там же.
   После каждого шага войти заново, открыть фото в карточке и каталоге, проверить
   checksum verifier. Это обязательная проверка persistence при пересоздании.
6. До включения на production записать результаты rehearsal и восстановительный
   путь. Само восстановление production выполняется только отдельно согласованной
   операцией с остановленными writes, текущим backup и проверенными checksum.

Rollback приложения сохраняет migration 0077, volume и аудит; старый совместимый
код может игнорировать additive поле. Downgrade 0077 запрещён, если существуют
фотографии **или** PHOTO_UPLOAD/PHOTO_DELETE история, даже после удаления всех фото.
Запрещено удалять историю ради downgrade.

## Проверено в этом задании

Локальная копия media восстановлена в другую временную директорию; verifier
проверил обе исторические версии после удаления текущей фотографии и обнаружил
контрольные повреждение/отсутствие файла. PostgreSQL и независимый backend process
проверены отдельно. Docker отсутствует в локальной среде: restart/recreate контейнера,
полный DB+volume recovery и production backup пока **не проверены**.
