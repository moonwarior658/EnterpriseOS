# K5B — review перед production update

09.10.2026, Asia/Yekaterinburg. Задание разрешает подготовку commit/push main,
но запрещает самостоятельный deployment. Production не изменяется.

## Проверка реализации

Проверены K5A report/evidence, K5B report/evidence, reader, collection/publication,
models/migration, existing authorization/automation seams и Compose/Dockerfile.
Source UUID identity, отсутствие catalog/Supply imports, Decimal, append-only
history, separate SOURCE/TREE/PREPARED и manual-only scope сохранены.
Технологические/денежные/производственные scope не расширены.

Новая migration 0078 безопасна по проверенному SQL и populated synthetic rehearsal:
создаёт только две новые пустые таблицы, индекс, function и triggers; меняет только
Alembic version. Нет backfill или изменения старых migrations. Downgrade отказывается
удалять заполненную историю. FK reference locks требуют bounded lock timeout в
maintenance window. Против существующей **реальной** production DB проверка ещё
не выполнена: fresh HEAD/head, permissions/collisions и rehearsal на restored
production backup — обязательные deployment gates.

Read-only SSH попытка не прошла authentication. GitHub connector подтвердил remote
main `a5a02823906ac467bceb8f98ad971377a5f31d6e`; прямые Git SSH/gh credentials
не работают. Commit/ref publication через авторизованный GitHub connector может
использоваться с expected parent/lease; никаких изменений access settings.
Точный release SHA выдаётся в передаче после публикации и повторного чтения ref.

## Пакет оператора

- [Windows runbook и критерии приёмки](STAGE_3_2_K5B_PRODUCTION_RUNBOOK_2026-10-09.md).
- `scripts/k5b_pilot.py`: preflight/resolve/export — SET TRANSACTION READ ONLY;
  enqueue — отдельная явная команда с Human TECHNICAL_ADMIN и existing outbox.
  Compare проверяет scope, новые observations, content version reuse, status,
  manifest и protected fingerprints. Соединения закрываются явно.
- [Release evidence](evidence/STAGE_3_2_K5B_RELEASE_2026-10-09.json): local checks,
  SQL hash, rehearsal summary и ограничения. Реальные source UUID и сырые ТТК
  в Git не включаются; operator export хранится приватно.

Выбраны три точно подтверждённых K5A root keys: `5fcc771dd5101343`,
`b22356f1bc446f77`, `47d5bdfb4b6f1aa7`. Первый проверяет nested и mainUnit кг/шт,
второй — другой nested root, третий — version transition 31.05/01.06 и проблемный
SPECIFIC/null sizes. Все root units — шт; разных root units K5A sample не доказывает.
Department key `a8e0fe727d8767fd`; warehouse/size неизвестны и остаются null.
Resolver выводит реальные UUID только при точном уникальном hash совпадении.
Сейчас реальные UUID не подтверждены повторно, никаких guessed UUID нет.

Четыре последовательных execution по **ровно трём** UUID: dated 09.10, повтор той
же даты/контекста, 31.05 и 01.06. Автоматический full batch и schedule отсутствуют.
Helper отказывается enqueue без head 0078 или при наличии recipe schedule.
Schema deployment и live-пилот выполняются только после решения владельца.

Техническая приёмка: smoke, backup/rehearsal, точный coverage/UUID/scope, Decimal,
зависимости/версии, history preservation, корректное качество, repeat reuse и
отсутствие domain mutations. Независимая приёмка: шеф/технолог сравнивает те же
UUID/department/date/store/size в **iikoOffice**, фиксирует норму и единицу каждой
строки, вложенные карты и две исторические даты. API-vs-API не заменяет Office.
Все ready_for_production=false, SPECIFIC остаётся блокированной до подтверждения.

## Валидация и состав commit

- Existing K5B local tests и новые helper tests: 19 PASS.
- PostgreSQL recipe/worker/immutability + operator read-only resolver: 3 PASS.
- Populated rehearsal 92 existing tables, 14 populated, fingerprints сохранены,
  empty recipe tables; cycle 0077/0078/0077/0078 PASS. Не production backup.
- Full backend suite: **1219 tests, OK, skipped=45**, 121.175 s.
  Финальный diff check PASS; SQL/источники и результаты в release evidence.
- Windows Docker build, backup/restore commands и production smoke не выполнялись.
- Temporary verification PostgreSQL удаляется после проверок.

В commit входят только K5B implementation/models/migration/automation seams,
profile tests/single-head assertion, K5B reports/evidence/runbook/helper и две
roadmap K5B entries. Ранее untracked **K5A report и K5A evidence не включаются**,
остаются локальными входными материалами без изменений. Их ссылки в историческом
K5B отчёте относятся к отдельному исходному пакету, не к опубликованным файлам
этого commit. Другие task files/секреты/.env/production artifacts не добавляются.

Остановка перед deployment: actual production compatibility, UUID resolution,
backup/rehearsal, live outcomes и Office verdict ещё не подтверждены. Наличие
release SHA и зелёных локальных тестов не закрывает эти gates.
