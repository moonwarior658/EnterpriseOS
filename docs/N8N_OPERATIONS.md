# Эксплуатация локального n8n

## Объём резервного копирования

`scripts/backup_n8n.ps1` создаёт custom-format дамп отдельной PostgreSQL n8n через `pg_dump` внутри сервиса `n8n-postgres`. Дампы сохраняются вне Docker volumes в `C:\eos\backups\n8n`.

Дамп содержит данные PostgreSQL n8n, но не заменяет защищённое хранение `.env`, `N8N_ENCRYPTION_KEY` и резервное копирование volume `n8n_data`. Для расшифровки credentials после восстановления нужен тот же encryption key. Если workflow сохраняют binary data в файловой системе, для него нужна отдельная политика резервного копирования `n8n_data`.

## Backup и retention

Ручной запуск из PowerShell на сервере:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\eos\scripts\backup_n8n.ps1 -RetentionDays 14
```

Скрипт всегда переходит в `C:\eos\docker\compose` и вызывает `docker compose --env-file ../../.env`. Дамп сначала создаётся и проверяется через `pg_restore --list`, копируется в файл `.tmp`, проверяется на ненулевой размер и только затем атомарно переименовывается в `n8n_yyyy-MM-dd_HH-mm-ss.dump`.

Retention по умолчанию — 14 дней. Удаляются только файлы `n8n_*.dump`, которые старше заданного срока; только что созданный дамп исключён из ротации. Значение меняется параметром `-RetentionDays`.

## Проверка backup и dry-run восстановления

Успешный backup уже включает `pg_restore --list`. Перед восстановлением обязательно повторить неразрушающую проверку:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\eos\scripts\restore_n8n.ps1 -BackupPath C:\eos\backups\n8n\n8n_YYYY-MM-DD_HH-mm-ss.dump -DryRun
```

Dry-run проверяет существование и размер файла, копирует его во временный путь контейнера, выполняет `pg_restore --list` и показывает план. Он не останавливает n8n и не изменяет БД.

## Реальное восстановление

Восстановление перезаписывает объекты БД n8n. Выполнять его только в согласованное окно обслуживания после успешного dry-run и проверки доступности исходного backup:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\eos\scripts\restore_n8n.ps1 -BackupPath C:\eos\backups\n8n\n8n_YYYY-MM-DD_HH-mm-ss.dump -ConfirmRestore
```

Скрипт останавливает только `n8n`, оставляет `n8n-postgres` доступным, выполняет `pg_restore --clean --if-exists --single-transaction`, запускает n8n и ожидает Docker health status `healthy`. Исходный backup не удаляется. Без `-ConfirmRestore` контейнеры и БД не изменяются.

Проверяемое восстановление следует периодически репетировать на изолированном тестовом экземпляре с отдельными volumes и копией обязательной конфигурации. `pg_restore --list` подтверждает читаемость архива, но не заменяет полный restore-drill.

## Health и безопасный restart

Проверка состояния сервисов:

```powershell
Set-Location C:\eos\docker\compose
docker compose --env-file ../../.env ps n8n n8n-postgres
docker inspect --format '{{.State.Health.Status}}' eos-n8n
docker inspect --format '{{.State.Health.Status}}' eos-n8n-postgres
```

PostgreSQL проверяется через `pg_isready`, n8n — через штатный `/healthz/readiness` без токенов и webhook. `n8n-postgres` использует `unless-stopped`; n8n — ограниченный `on-failure:5`, чтобы постоянная ошибка запуска или миграции не создавала бесконечный crash-loop. После исчерпания попыток нужно сначала изучить безопасные логи и устранить причину, затем явно запустить сервис.

## Ежедневный Scheduled Task

Команда для создания запуска каждый день в 02:30 по локальному времени Windows Server (выполнить вручную из повышенного PowerShell; в репозитории задача автоматически не создаётся):

```powershell
schtasks.exe /Create /TN "EnterpriseOS n8n Backup" /SC DAILY /ST 02:30 /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\eos\scripts\backup_n8n.ps1 -RetentionDays 14" /RU SYSTEM /RL HIGHEST /F
```

После создания проверить результат ручным запуском задачи и наличие нового ненулевого `.dump`, а затем проверить журнал Task Scheduler и код завершения `0`.

## Ошибки, ротация и ориентиры восстановления

При ошибке backup временный host-файл удаляется, итоговый файл не публикуется, скрипт возвращает ненулевой код. Не ослаблять права на `.env` и backup-каталог, не помещать дампы в Git и не удалять последний проверенный backup при ручной ротации. Для защиты от отказа самого диска нужна дополнительная шифрованная копия в отдельном хранилище с контролем доступа.

При ежедневном успешном backup ориентир RPO — до 24 часов плюс время до обнаружения сбоя задания. RTO зависит от размера БД, скорости диска, исправности Docker и времени диагностики; гарантированное значение можно установить только после измеренного restore-drill. При неуспешном restore не повторять его вслепую: сохранить исходный дамп, проверить состояние `n8n-postgres`, health и безопасные логи, затем устранить причину.
