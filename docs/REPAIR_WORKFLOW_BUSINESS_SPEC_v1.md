# EnterpriseOS — Repair Workflow Business Spec v1

**Тип документа:** BUSINESS SPEC
**Статус:** CURRENT / IMPLEMENTED — baseline eb59755
**Дата актуализации:** 06.10.2026
**Область:** ответственность, исполнение, эскалация и завершение ремонтов

Связанные документы:

- [Access Control and Role Hierarchy v1](ACCESS_CONTROL_AND_ROLE_HIERARCHY_v1.md) — разрешения и scope ролей.
- [Stage 3.1P — Пользователи и ответственность](STAGE_3.1P_USERS_AND_RESPONSIBILITY_BUSINESS_SPEC.md) — User/Employee identity, iiko shift, ActionContext и аудит.

Матрица role + action + scope определяется Access Control. Этот документ задаёт процесс ремонта и не создаёт новые роли или permissions.

## 1. Общая ответственность

Любая роль, которой матрица доступа разрешает создать repair в данном scope, после создания видит полную карточку: автора, подразделение, описание, фотографии, комментарии, статус, историю, исполнителя, изменения статуса и вложения.

Новая repair request автоматически назначается HANDYMAN. HANDYMAN ведёт ремонт и закрывает его, если выполняет самостоятельно. Подробные действия каждой роли ограничены матрицей доступа.

## 2. Выполнение HANDYMAN и подрядчик

Если HANDYMAN не может выполнить ремонт самостоятельно, он выбирает specialization и contractor и получает имя/телефон для связи.

После связи доступны два отдельных действия:

### «Мастер придёт»

- подрядчик подтверждён;
- visit datetime обязательна;
- HANDYMAN остаётся ответственным;
- визит отображается в «Назначенные события» Dashboard;
- HANDYMAN продолжает вести repair и закрывает его после выполнения.

### «Не смог назначить время — передать руководителю»

- ответственность полностью переходит SUPPLY_MANAGER;
- HANDYMAN перестаёт быть ответственным;
- дополнительная reason не требуется, поскольку причина задана типом явного действия.

## 3. External Contractor и specialization

ExternalContractor — отдельная сущность, не Employee и не User. Минимальные поля: name/company, phone, active, comment, несколько specializations и repair history.

Specialization — отдельный справочник; у подрядчика может быть несколько специализаций. Примеры: electrician, refrigeration, plumber, doors, ventilation, universal handyman.

Каталог contractor/specialization могут изменять только ADMIN и SUPPLY_MANAGER. Остальные роли выбирают contractor только в разрешённом repair process. Все изменения contractor и specialization аудируются. Правила обязательной причины для supplier применяются к supplier; для contractor отдельное правило обязательной причины не утверждено.

## 4. Передача SUPPLY_MANAGER

После эскалации SUPPLY_MANAGER становится ответственным за ремонт, выбирает/подтверждает contractor, связывается с ним, назначает visit datetime, видит визит в Dashboard и ведёт ремонт до закрытия после выполнения.

После закрытия инициирующий scope проверяет результат и может переоткрыть ремонт, если результат не принят. Переоткрытие требует обязательной причины. Management role своего scope также может переоткрыть ремонт по матрице доступа.

## 5. Закрытие и переоткрытие

- HANDYMAN закрывает ремонт, который выполнил/вёл.
- SUPPLY_MANAGER закрывает ремонт после принятой ответственности и выполнения.
- NETWORK_MANAGER, HEAD_OF_PRODUCTION, DEPUTY_DIRECTOR и иные роли не получают права закрывать только из факта создания или управления; применяются конкретные permissions матрицы.
- Инициирующий контур может переоткрыть закрытый ремонт при непринятом/некачественном результате; reason обязательна.
- SELLER может переоткрыть свой repair; NETWORK_MANAGER — любой repair точек Эклер.
- CHEF_CONFECTIONER может переоткрыть repair своего производства; HEAD_OF_PRODUCTION — любой repair производства.
- DRIVER может переоткрыть инициированный им ремонт после плохого результата.
- CONFECTIONER и BAKER могут переоткрыть созданный ими repair при плохом результате.
- SUPPLY_MANAGER может переоткрыть в пределах разрешённого repair scope по матрице.

## 6. CURRENT — visit_at и Dashboard; TODO — общие reminders

Время визита сохраняется как `visit_at`; upcoming external visits отображаются
в «Назначенные события» Dashboard из доступных пользователю EOS repairs.
Это внутренний operational блок без зависимости от Telegram/email.

Общая доставка internal reminders, SLA, missed visit, повторные напоминания,
overdue escalation и checklists — **TODO / DEFERRED** отдельного contour.
Наличие visit_at и Dashboard card не означает отправленного reminder.

## 6.1. CURRENT — стоимость и документы внешнего ремонта

- Repair связан с ExternalContractor через contractor_id, а также specialization;
  карточка contractor сохраняет repair history. Передача ответственности и
  переоткрытие не удаляют историю.
- `repair_cost`, invoice (`INVOICE`) и completion act (`ACT`) сохраняются в repair.
  Документы можно загрузить до/после close, сумму можно добавить после close.
- Completed external repair без cost или любого из INVOICE/ACT = «Требует действий»
  в карточке/реестре; Dashboard показывает «Требует внимания» для доступных ролям
  business entities.
- Financial visibility: ADMIN, DIRECTOR, DEPUTY_DIRECTOR, SUPPLY_MANAGER,
  ACCOUNTANT видят сумму/финансовые документы; добавляют ADMIN/SUPPLY_MANAGER/ACCOUNTANT
  в доступном repair scope. HANDYMAN и остальные не получают financial data.
- Payment автоматически из Repair **не создаётся**. Repair cost и SupplierPayment
  не подменяют друг друга; отдельная оплата ремонта не объявляется реализованной.

Details/status/history/документы остаются под authoritative backend allowed_actions
и ActionContext; финансовое дополнение не переоткрывает repair автоматически.

## 7. Аудит

Создание, назначение/передача ответственности, изменение статуса, закрытие и переоткрытие сохраняют аудит согласно Stage 3.1P и Access Control. Переоткрытие сохраняет обязательную причину. История ремонта не удаляется при передаче или повторном открытии.
