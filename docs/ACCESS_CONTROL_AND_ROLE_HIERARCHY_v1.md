# EnterpriseOS — Access Control and Role Hierarchy v1

**Тип документа:** BUSINESS SPEC
**Статус:** CURRENT / IMPLEMENTED — 13 ролей, baseline eb59755; Stage 3.1P DONE
**Дата актуализации:** 06.10.2026
**Область:** роли, разрешения, области данных и видимость интерфейса EOS

## 1. Назначение и нормативность

Документ задаёт единую матрицу доступа EOS: иерархию ролей, permissions, data scope, назначение ролей, работу нескольких ролей, `authorized_as`, видимость интерфейса, доступ к Employee/User, Dashboard и Audit Explorer, а также обязательные причины административных действий.

Связанные документы:

- [Stage 3.1P — Пользователи и ответственность](STAGE_3.1P_USERS_AND_RESPONSIBILITY_BUSINESS_SPEC.md) — идентичность User/Employee, история назначений, iiko identity/shifts, ActionContext и основа аудита.
- [Roadmap Stage 3 Supply](ROADMAP_STAGE_3_SUPPLY_v0.1.0.md) — утверждённая последовательность и lifecycle Supply.
- [Repair Workflow Business Spec v1](REPAIR_WORKFLOW_BUSINESS_SPEC_v1.md) — процесс ремонта, передача ответственности, подрядчики и напоминания.

Если прежняя формулировка матрицы доступа противоречит этому утверждённому документу, применяется данный документ. Он не меняет историческое описание того, что было реализовано или проверено ранее. Supply lifecycle остаётся в Roadmap Stage 3 Supply; этот документ определяет доступ к нему.

## 2. Главный принцип

**Role отвечает на вопрос «что можно делать». Scope отвечает на вопрос «с какими объектами это можно делать».** Разрешение требует одновременно подходящей роли и разрешённого scope. Backend является окончательной точкой контроля; frontend скрывает недоступные разделы и действия.

Фиксированные роли ниже не являются конструктором permissions. Новые роли и права этим документом не вводятся.

## 3. Каталог ролей и смысловая иерархия

Используются только существующие роли: `ADMIN`, `DIRECTOR`, `DEPUTY_DIRECTOR`, `ACCOUNTANT`, `SUPPLY_MANAGER`, `DRIVER`, `HANDYMAN`, `NETWORK_MANAGER`, `CHEF_CONFECTIONER`, `CONFECTIONER`, `BAKER`, `HEAD_OF_PRODUCTION`, `SELLER`.

```text
ADMIN
├── DIRECTOR
└── DEPUTY_DIRECTOR
    ├── NETWORK_MANAGER
    ├── HEAD_OF_PRODUCTION
    │   └── CHEF_CONFECTIONER
    │       ├── CONFECTIONER
    │       └── BAKER
    ├── SUPPLY_MANAGER
    └── ACCOUNTANT

Исполнительские роли: HANDYMAN, DRIVER, SELLER
```

Это смысловая иерархия полномочий, а не обязательная оргструктура подчинения. Положение в иерархии само по себе не даёт прав другой роли.

## 4. Scope catalog

- `ALL_COMPANY` — все бизнес-объекты компании в явно разрешённых для роли модулях.
- `ECLAIR_POINTS` — павильоны Эклер и относящиеся к ним объекты.
- `PRODUCTION` — текущее производственное подразделение (сейчас одно).
- `PRIMARY_DEPARTMENT` — действующее основное подразделение Employee.
- `ACTUAL_SHIFT_DEPARTMENT` — подразделение разрешённой активной смены iiko; для Seller имеет приоритет в рабочем контексте.
- `ASSIGNED_OBJECTS` — объекты, назначенные конкретному Employee.
- `ASSIGNED_TRANSPORTS` — перевозки, назначенные конкретному Driver.
- `ESCALATED_REPAIRS` — ремонты, ответственность за которые передана Supply Manager.
- `OWN_CREATED_OBJECTS` — объекты, созданные самим пользователем/его рабочим контекстом.

Scope ограничивает объекты, но сам по себе не добавляет действия. Где права зависят от модуля, применяются и модульное разрешение, и scope.

## 5. Назначение ролей

| Назначающий | Может назначать |
|---|---|
| `ADMIN` | Любые перечисленные роли; только ADMIN назначает ADMIN |
| `DIRECTOR` | Не назначает роли |
| `DEPUTY_DIRECTOR` | NETWORK_MANAGER, HEAD_OF_PRODUCTION, SUPPLY_MANAGER, ACCOUNTANT, CHEF_CONFECTIONER, HANDYMAN, DRIVER, SELLER, CONFECTIONER, BAKER |
| `NETWORK_MANAGER` | Только SELLER, DRIVER, HANDYMAN |
| Остальные роли | Не назначают роли |

Назначения и снятия ролей имеют историю и аудит. Для них обязательна содержательная причина. DEPUTY_DIRECTOR не назначает ADMIN, DIRECTOR или DEPUTY_DIRECTOR.

## 6. Несколько ролей и `authorized_as`

У одного Employee может быть несколько активных ролей.

1. Разрешения активных ролей объединяются.
2. READ выполняется в самом широком scope, который явно разрешён активной ролью для данного ресурса.
3. Более широкий READ одной роли не расширяет WRITE другой роли: WRITE ограничен scope роли, которая разрешает действие.
4. Если действие явно разрешено хотя бы одной активной ролью, оно может быть выполнено через эту роль при соблюдении её scope и остальных ограничений.
5. Каждое write-action фиксирует одну конкретную `authorized_as` — активную роль, на основании которой разрешено именно это действие. Нельзя выводить её только из иерархии или выбирать произвольную неактивную роль.
6. Аудит сохраняет User, Employee, активные роли, `authorized_as`, primary department, actual department и iiko shift, если применимо.

Проверка permissions и scope выполняется на backend для каждого чтения/изменения, включая прямые API-запросы.

## 7. Матрица ролей

### 7.1 ADMIN

**Scope:** `ALL_COMPANY`. Полный доступ к бизнес-функциям и администрированию EOS: Employee, Human User, Service User, роли, подразделения, пароли, блокировки, iiko mappings, Audit Explorer, automation, техническая диагностика n8n/worker, suppliers, contractors и system settings. Физически изменять или удалять audit trail нельзя и ADMIN.

### 7.2 DIRECTOR

**Scope:** `ALL_COMPANY`; глобальный business read-only. Читает все подразделения и бизнес-данные: ремонты, Supply/procurement, suppliers, orders, acceptances, payments, debts, документы, employees/users и финансовую информацию. Не изменяет бизнес-данные и настройки.

Не имеет доступа к Audit Explorer, iiko technical mappings, automation internals, n8n/worker и технической инфраструктуре. Будущие business summaries являются отдельной последующей работой.

### 7.3 DEPUTY_DIRECTOR

**Scope:** `ALL_COMPANY`. Читает всю бизнес-часть. Может редактировать и увольнять Employee, менять роли и подразделения. Видит существующих Human Users, может блокировать и активировать их; не создаёт Human User, не сбрасывает пароль и не управляет Service User.

Ремонты: может создавать и видеть полную карточку; после создания не редактирует и не закрывает; может переоткрыть инициированный им ремонт при некачественном выполнении. Supply: читает, но не создаёт SupplyRequest. Не имеет доступа к Audit Explorer, iiko technical mappings и automation/n8n/worker.

### 7.4 NETWORK_MANAGER

**Scope:** `ECLAIR_POINTS`. Dashboard павильонов Эклер. Видит ремонты контура, создаёт их, видит полную карточку и может переоткрыть любой ремонт контура; не закрывает. Видит только SupplyRequest точек Эклер и может создавать заявки для павильонов; не видит финансовый/закупочный Supply-контур.

Видит сотрудников контура, может создавать и редактировать Employee, создавать Human User, связывать User↔Employee и сбрасывать пароль Human User своего контура. Не увольняет, не блокирует и не активирует User. Может назначать/менять рабочую точку; перевод требует даты вступления в силу и обязательной причины, история сохраняется. Может назначать только SELLER, DRIVER, HANDYMAN.

Не видит finances, payments, debts, suppliers, Audit Explorer, iiko technical mappings, automation, n8n или worker.

### 7.5 HEAD_OF_PRODUCTION

**Scope:** `PRODUCTION` (сейчас одно производственное подразделение). Dashboard производства. Видит все ремонты производства, создаёт и переоткрывает их, не закрывает. Видит Supply производства, создаёт, редактирует и отменяет заявки производства; видит связанные закупки, позиции, цены и суммы. Видит сотрудников производства в базовом профиле, не редактирует Employee и не назначает роли. Не видит павильоны.

### 7.6 SUPPLY_MANAGER

**Scope:** весь Supply-контур компании. Dashboard: supply, debts, payments, repairs. Имеет полный operational access к цепочке `SupplyRequest → ProcurementNeed → PurchaseRequest → SupplierAllocation → SupplierOrder → SupplierConfirmation → SupplierDocument → SupplierAcceptance → SupplyIikoIncomingReceipt → Internal Transfer → Payment/Settlement → iiko business facts` в пределах существующего Supply workflow.

Может создавать SupplyRequest и редактировать чужие SupplyRequest только с обязательным комментарием и аудитом; не отменяет SupplyRequest точек. Может создавать PurchaseRequest, управлять supplier records и supplier orders, acceptance, internal transfers и payments согласно Supply lifecycle.

Видит ремонты и является руководителем контура DRIVER/HANDYMAN. При передаче ремонта HANDYMAN принимает полную ответственность по [Repair Workflow](REPAIR_WORKFLOW_BUSINESS_SPEC_v1.md). Видит базовые рабочие профили DRIVER/HANDYMAN; кадровые данные и роли не меняет. iiko technical mapping section не видит; использует только business facts.

### 7.7 ACCOUNTANT

**Scope:** вся компания в пределах финансовых и Supply-данных. Dashboard — только финансы. Имеет полный READ всей цепочки SupplyRequest точки → supplier order/acceptance/payment/debt. Supply WRITE разрешён для payments и редактирования supplier;
в repairs доступны стоимость/финансовые документы внешнего ремонта.

Видит prices, sums, cost, debts, invoices, УПД, bills, supplier documents и acceptance/payment documents. Не видит internal transfers, Employee admin, Audit Explorer, iiko mappings, automation/n8n/worker. Repair workflow/status — read-only; стоимость и INVOICE/ACT может добавлять по financial permissions, включая closed repair.

### 7.8 CHEF_CONFECTIONER

**Scope:** текущее производственное подразделение. Dashboard своего производства. Видит ремонты, создаёт их, видит полную карточку и переоткрывает. Видит Supply, создаёт потребности/SupplyRequest, редактирует и отменяет заявки своего подразделения. Читает закупки, созданные из её потребностей, включая статус, позиции, цены и суммы. Не управляет suppliers, payments или employees.

### 7.9 HANDYMAN

**Scope:** `ALL_COMPANY` для repairs; department scope не ограничивает доступ к ремонтам. Dashboard repairs. Видит полные карточки всех ремонтов, создаёт, берёт в работу, меняет статус, добавляет comments/photos и закрывает. Не видит Supply, prices или financial data.

### 7.10 DRIVER

**Primary Department:** Авто; дополнительных подразделений нет. Dashboard — назначенные перевозки и Авто. Может создать ремонт в контуре Авто, видеть инициированный им ремонт и переоткрыть после плохого результата. Видит только назначенные ему перевозки и данные груза (что, количество, откуда, куда); меняет статус и подтверждает получение/передачу. Не видит prices, sums, suppliers, чужие transports или SupplyRequest.

**Статус реализации 01.10.2026:** достоверной связи `InternalTransfer/TransportTask → Driver Employee` в текущей модели нет. Доступ DRIVER к перевозкам и Internal Transfer отложен до отдельного решения об источнике назначения; общий список transfer ему не открывается.

### 7.11 SELLER

У SELLER только одна активная назначенная точка; дополнительные активные точки запрещены. При переводе старое назначение закрывается датой, новое начинается своей датой; допускается будущая дата, старые business facts не переписываются.

Без активной iiko-смены repair scope чтения — `PRIMARY_DEPARTMENT`, режим read-only.
SupplyRequest: доступны собственные заявки и заявки рабочей/основной точки;
TEMPORARY writes могут использовать выбранную RETAIL_POINT. С активной сменой рабочий scope — `ACTUAL_SHIFT_DEPARTMENT`, который имеет приоритет над primary. Этот gate применяется к shift-required repair writes; временное правило SupplyRequest описано ниже.

Ремонты: видит полную карточку в разрешённом контуре, создаёт, редактирует и переоткрывает; не закрывает. Supply: видит заявки точки, создаёт, редактирует свою; не отменяет, не видит downstream procurement/orders, prices или sums. Shift-required repair write без активной resolved смены запрещён.

**TEMPORARY — SupplyRequest:** создание/изменение/подтверждение своей заявки
разрешены в открытом окне без проверки активной смены и назначенного department.
Seller вручную выбирает активную RETAIL_POINT tenant; backend проверяет role,
identity, ownership, window и version/duplicates. Cycle/direction/date системные.
Это исключение не расширяет repair permissions или downstream read. Детали и
TODO work-context policy — [Supply spec](eOS_STAGE_3_SUPPLY.md#32-temporary--выбор-точки).

### 7.12 CONFECTIONER и BAKER

Исполнительские роли текущего производственного подразделения. Каждая может создать repair и затем видеть полную карточку инициированного ремонта; может переоткрыть его при плохом результате. Не видит общий repair list, Supply, procurement, prices, sums или admin functionality. Остальные производственные права не расширяются этим пунктом.

## 8. Employee data visibility

Полный Employee profile доступен ADMIN; DIRECTOR — read-only; DEPUTY_DIRECTOR; NETWORK_MANAGER — только своего контура. HEAD_OF_PRODUCTION видит базовый профиль сотрудников производства. SUPPLY_MANAGER видит базовые рабочие профили DRIVER/HANDYMAN. Другие роли видят базовый профиль только при принадлежности Employee к их рабочему контексту.

Базовый профиль содержит ФИО, фото, дату рождения, телефон, role/title и department. Он не содержит адреса проживания, административной истории или технических данных учётной записи. Полный профиль не означает право на технические секреты или пароли.

## 9. User accounts и пароли

- ADMIN управляет Human и Service Users полностью.
- DIRECTOR читает account information без изменений.
- DEPUTY_DIRECTOR читает существующих Human Users, блокирует/активирует их; не создаёт пользователя, не сбрасывает пароль и не управляет Service User.
- NETWORK_MANAGER создаёт Human User в своём контуре, связывает с Employee и сбрасывает ему пароль; не блокирует и не активирует User и не управляет Service User.
- Service User доступны только ADMIN.
- Authenticated HUMAN меняет собственный пароль без current password: новый +
  confirmation в UI; API `/auth/change-password` изменяет только текущего User.
  Arbitrary чужой User этим flow менять нельзя; SERVICE forbidden.
  USER_PASSWORD_CHANGED audit event не содержит password/hash.
- Основной Human account lifecycle выполняется из Employee card. `/users` —
  сохраняющийся legacy route; Employee — человек, User — access account.
  HUMAN связан с Employee, SERVICE связывать запрещено.
- Сброс пароля не требует причины; учётные данные и секреты не включаются в аудит.

## 10. Dashboard и видимость UI

| Роль | Dashboard |
|---|---|
| ADMIN | Всё |
| DIRECTOR | Глобальная business read-only сводка |
| DEPUTY_DIRECTOR | Глобальная operational сводка |
| NETWORK_MANAGER | Павильоны Эклер |
| HEAD_OF_PRODUCTION | Производство |
| SUPPLY_MANAGER | Supply, debts, payments, repairs |
| ACCOUNTANT | Финансы |
| CHEF_CONFECTIONER | Своё производство |
| HANDYMAN | Ремонты |
| DRIVER | Назначенные перевозки и Авто |
| SELLER | Текущая/основная точка в пределах правила смены |
| CONFECTIONER, BAKER | Минимальная рабочая главная страница без лишней аналитики |

Если разрешения на раздел нет, раздел не показывается в меню. Если действие запрещено, кнопка не показывается. UI не должен направлять пользователя к действию, которое завершится ожидаемым 403. Backend независимо проверяет permission и scope для каждого запроса.

## 11. Audit visibility и event

Audit Explorer доступен только ADMIN. DIRECTOR и DEPUTY_DIRECTOR не видят raw audit; business summaries для них — отдельная будущая работа. Доступ к бизнес-истории объекта в разрешённом модуле не является доступом к глобальному Audit Explorer. Значимые действия в реализованных API flows аудируются атомарно с business mutation;
unknown legacy attribution не достраивается по сегодняшним назначениям.

Значимое audit-событие содержит actor User, actor Employee, активные роли, `authorized_as`, object/entity, operation, before, after, reason когда требуется, primary department, actual department, shift если применимо и timestamp. Audit trail append-only: физическое изменение/удаление запрещено даже ADMIN; исправление оформляется отдельным связанным событием.

## 12. Обязательная причина

Причина обязательна для:

- изменения/перевода подразделения;
- назначения или снятия роли;
- блокировки User и активации User;
- увольнения Employee;
- редактирования чужого SupplyRequest SUPPLY_MANAGER;
- переоткрытия ремонта;
- критичного изменения supplier и деактивации supplier;
- изменения уже проведённого/существующего payment, отмены payment, исправления суммы, даты или связи payment.

Причина не обязательна для сброса пароля, создания payment, обычного некритичного изменения контакта supplier и явного действия HANDYMAN «Не смог назначить время — передать руководителю».

Обычные изменения supplier сохраняют before/after audit. Критичные изменения supplier сохраняют before/after и обязательную reason. Создание payment аудируется без обязательной reason; correction/cancel/update аудируются с обязательной reason.

## 13. Repair access boundary

CURRENT repair cost и финансовые INVOICE/ACT видят ADMIN, DIRECTOR,
DEPUTY_DIRECTOR, SUPPLY_MANAGER, ACCOUNTANT. Изменяют ADMIN/SUPPLY_MANAGER/ACCOUNTANT
в доступном repair scope; остальные получают фотографии и безопасную историю
без финансовых полей. «Полная карточка» ниже не расширяет financial permissions.

Любая роль, которой матрица разрешает создать repair, получает полную карточку созданного/видимого в её scope ремонта: author, department, description, photos, comments, status, history, assignee, status changes и attachments. Ответственность, назначение HANDYMAN, contractors, escalation, takeover, close/reopen и reminders определяются отдельно в [Repair Workflow Business Spec v1](REPAIR_WORKFLOW_BUSINESS_SPEC_v1.md).
