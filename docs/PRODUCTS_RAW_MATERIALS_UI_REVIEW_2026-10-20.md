# «Продукция» ↔ «Сырьё»: UI review

База: `32114f407bda7ea4926bdb97e294a0387591a9ed`. Ветка: `feature/product-materials-ui`.
Локальная реализация; push, deployment и обращения к production не выполнялись.

## Разведка и переиспользование

Страницы ProductKnowledgePage и RawMaterialsPage используют разные предметные API. Общими уже были EosDialog и EosFormControls (поиск, select, дата, пагинация). Реализация MaterialDialog и форматтеры перенесены в KnowledgeDialog и knowledgePresentation; прежние импорты «Сырья» сохранены через re-export. CSS «Сырья» перенесён в единый KnowledgeUI.css, обе страницы подключают один набор правил. MaterialEditor и ProductPhotoEditor используют общий выбор файла.

Практические общие компоненты: KnowledgeHeader, KnowledgeActions, KnowledgeInfo, KnowledgeStatus, KnowledgeFilterToggle, KnowledgeSortHeader, KnowledgePhoto, KnowledgePhotoPicker, KnowledgeDialog. Общие форматтеры: knowledgeNumber, knowledgePeriod. История использует общий диалог, но сохраняет собственные API и представление событий каждого раздела.

## Сравнительный checklist

PASS ниже означает проверку кодом и автоматическими тестами, не визуальную бизнес-приёмку.

| Элемент | «Сырьё» ↔ «Продукция» | Результат |
|---|---|---|
| Заголовок, описание | Общий KnowledgeHeader | PASS |
| Действия в шапке | Общий KnowledgeActions; доступные операции из backend | PASS |
| Поиск, select, дата | Существующие EosFormControls; фильтры продукции сохранены | PASS |
| Переключатели фильтров | Общий KnowledgeFilterToggle, aria-pressed | PASS |
| Таблица, отступы, типографика | Единый CSS; все колонки продукции сохранены | PASS по коду; визуальная проверка ожидается |
| Сортировка | Общий заголовок; продукция сортируется до пагинации с сохранением фильтров | PASS frontend/API/PG |
| Числа | Общий десятичный форматтер; точные нормы и расчёты не изменены | PASS |
| Фотографии, пустые состояния | Общий KnowledgePhoto; защищённая загрузка продукции сохранена | PASS |
| Пагинация | Существующий EosPagination, 25 строк | PASS |
| Mobile | Единая таблица с горизонтальной прокруткой, адаптивная карточка | Реализовано; браузерная проверка не выполнена |
| Карточка | Read-only сведения, фото и общий информационный блок | PASS |
| Редактирование | Общий диалог; поля продукции и expected_version сохранены | PASS |
| Сохранение и отмена | Dirty guard, продолжение/отмена, сброс черновика при закрытии | PASS |
| Защита повторной отправки | Сохранён submit lock и busy | PASS |
| Фотография | Общий picker и диалог; старые загрузка/удаление и ограничения | PASS |
| История | Общий диалог; события/пагинация продукции сохранены | PASS |
| Дополнительные сведения | Цены, ТТК и ССН в отдельных общих диалогах | PASS |
| Права | Existing allowed_actions/cost_access/recipe_access, защита cost sort backend | PASS |
| Регрессия сырья | Старые импорты совместимы, текущие тесты входят в полный frontend suite | PASS |
| Desktop/mobile в браузере | CUA inventory: browsers=[], apps=[] | НЕ ВЫПОЛНЕНО |

## Что нельзя объединять без изменения предметной модели

- Колонки и фильтры: продукция имеет тип продажи, статус ассортимента, точку и дату цены; сырьё — поставщиков, приходные факты, среднюю и расход. Сырьевые колонки в продукцию не добавлены.
- Цены: цена продажи относится к выбранной точке и дате; закупочная цена сырья имеет документное основание. Сохранены конфликты, отсутствие цены и признаки устаревания, без подстановок.
- Редактирование и подтверждение: продукция имеет отметку «Проверено», soft delete/restore; сырьё — версии и утверждение спецификаций. Общая оболочка не объединяет команды и права.
- Добавление: продукция подтверждается по source_id + UUID iiko + confirmation_hash; сырьё включается из существующего SupplyProduct. Сопоставления по названию не добавлены.
- ТТК и ССН: сохранены существующие контексты, точные нормы, evidence и допуск VERIFIED. Изменено только размещение и уведомление диалога о dirty/busy.
- История: разные типы событий и API пагинации. Общий диалог переиспользован, доменные записи не преобразованы в искусственную общую модель.

## API и данные

Единственное расширение API — необязательные sort/direction у GET каталога продукции: name, unit_weight_kg, sale_mode, price, cost, sale_status; asc/desc. Старый запрос сохраняет сортировку по имени. Цена сортируется только из доступной выбранной точки, конфликтные значения считаются неизвестными. Себестоимость используется только VERIFIED и при существующем cost_access; попытка сортировки без права возвращает 403. Неизвестные значения идут последними в обоих направлениях. Tenant/point scope сохранён.

Миграций, новых зависимостей и изменения схемы нет. Расчёты, склад, iiko-интеграция, Supply, K5C и бизнес-данные не изменены. Для вычисляемых сортировок сервер проецирует отфильтрованный каталог до пагинации; при значительном росте каталога потребуется отдельная оценка производительности.

## Проверки

- Frontend: `npm test` — 230/230 PASS, включая новые 4 UI integration tests и прежние сценарии продукции/сырья.
- `npm run build` — PASS; предупреждение о размере JS chunk остаётся.
- ESLint всех изменённых TS/TSX и новых файлов — PASS. AuthContext не изменён.
- Backend full suite: 1312 tests, OK, 68 skipped (опциональные окружения).
- Targeted backend (catalog order + product knowledge): 16/16 PASS.
- Реальная изолированная PostgreSQL: 4/4 целевых теста PASS — глобальная сортировка/tenant/point scope, concurrency, retry, constraints, ручное добавление по UUID.
- Дополнительный запуск двух старых PG-модулей: 4 PASS / 2 FAIL. Старые downgrade-тесты ожидают защиту K1/K2, но на уже заполненной схеме 0083 сначала корректно срабатывает MATERIAL_ADMISSION_HISTORY_EXISTS. Это ограничение старых тестов/фикстуры; migrations и downgrade-правила не менялись. Ошибки не скрыты изменением ожиданий.
- `git diff --check` — PASS.
- Браузерная визуальная проверка desktop/mobile не выполнена: подключённых браузеров нет. JSDOM не считается браузерной приёмкой.

## Состав файлов

- Frontend components: KnowledgeUI.tsx/css, KnowledgeDialog.tsx, knowledgePresentation.ts; совместимые MaterialDialog/materialPresentation; MaterialEditor.
- Frontend pages: ProductKnowledgePage, RawMaterialsPage/css; ProductManagement, ProductPhoto, ProductCosts, ProductRecipes.
- Frontend services: productKnowledge, productCosts (только отображение).
- Backend: product_knowledge route/service/catalog_order (сортировка каталога).
- Tests: productUnifiedUi; адаптация productKnowledgeLive/productKnowledgeManagement/productPhotos к модальным окнам; test_product_catalog_order, test_product_knowledge, test_product_knowledge_postgres.

Остановка на review. Для визуальной приёмки нужны подключённый браузер и тестовое окружение; production не изменён.
