import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  cancelSupplyRequest,
  disableSupplyAlias,
  confirmSupplyDebtInclusion,
  fulfillSupplyAsPlanned,
  getSupplyProducts,
  getSupplyRequest,
  getSupplyUnits,
  matchSupplyLine,
  planSupplyRequest,
  saveSupplyAllocations,
  saveSupplyFulfillment,
  saveSupplyLineWorkingValues,
  SupplyApiError,
  type SupplyLine,
  type SupplyProduct,
  type SupplyRequest,
  type SupplyUnit,
} from '../services/supplyAdmin'
import {
  clearSupplyLineMappingDraft,
  clearSupplyLineWorkingDraft,
  createSupplyLineWorkingDraft,
  getSupplyLineMappingDraft,
  getSupplyLineWorkingDraft,
  suggestSupplyWorkingName,
  updateSupplyLineMappingDraft,
  updateSupplyLineWorkingDraft,
  type SupplyLineMappingState,
  type SupplyLineWorkingState,
} from './supplyRequestDetailLogic'

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'long', timeStyle: 'short',
  }).format(new Date(value))
}

function AllocationEditor({
  request,
  line,
  onSaved,
}: {
  request: SupplyRequest
  line: SupplyLine
  onSaved: (request: SupplyRequest) => void
}) {
  const initial = useMemo(() => ({
    transfer: line.allocations.length ? line.planned_transfer : (line.quantity ?? ''),
    purchase: line.planned_purchase === '0.000' ? '' : line.planned_purchase,
    cancel: line.planned_cancel === '0.000' ? '' : line.planned_cancel,
    comment: line.allocations[0]?.comment ?? '',
  }), [line])
  const [values, setValues] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState(line.allocations.length ? 'Сохранено' : 'Предложение, не сохранено')
  const dirty = JSON.stringify(values) !== JSON.stringify(initial)
  const requested = Number(line.quantity ?? 0)
  const total = Number(values.transfer || 0) + Number(values.purchase || 0) + Number(values.cancel || 0)
  const remaining = Math.max(requested - total, 0)

  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  async function save() {
    if (!line.requested_unit || saving) return
    setSaving(true)
    setMessage('')
    try {
      const updated = await saveSupplyAllocations(
        request.id, line.id, request.version, values, line.requested_unit.id,
      )
      onSaved(updated)
    } catch (error) {
      setMessage(error instanceof SupplyApiError && error.code === 'SUPPLY_REQUEST_VERSION_CONFLICT'
        ? 'Заявка изменилась. Обновите карточку и повторите.'
        : 'Не удалось сохранить решение')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="supply-allocation-editor">
      {(['transfer', 'purchase', 'cancel'] as const).map((key) => (
        <label key={key}>
          <span>{({ transfer: 'Перемещение', purchase: 'Закупка', cancel: 'Отмена' })[key]}</span>
          <input
            type="number" min="0" step="0.001"
            value={values[key]}
            disabled={saving || !['SUBMITTED', 'IN_REVIEW'].includes(request.status)}
            onChange={(event) => setValues({ ...values, [key]: event.target.value })}
          />
        </label>
      ))}
      <label className="supply-comment">
        <span>Комментарий</span>
        <input value={values.comment} disabled={saving} onChange={(event) => setValues({ ...values, comment: event.target.value })} />
      </label>
      <span className={remaining ? 'supply-incomplete' : 'supply-complete'}>
        Не распределено: {remaining.toFixed(3)}
      </span>
      <button type="button" disabled={saving || total > requested || !dirty} onClick={() => void save()}>
        {saving ? 'Сохраняем…' : 'Сохранить решение'}
      </button>
      <small>{total > requested ? 'Распределено больше запрошенного' : message}</small>
    </div>
  )
}

function FulfillmentEditor({
  request,
  line,
  onSaved,
}: {
  request: SupplyRequest
  line: SupplyLine
  onSaved: (request: SupplyRequest) => void
}) {
  const physical = useMemo(
    () => line.allocations.filter(
      (allocation) => allocation.action !== 'CANCEL',
    ),
    [line.allocations],
  )
  const initial = useMemo(() => Object.fromEntries(
    physical.map((allocation) => [
      allocation.id,
      {
        quantity: allocation.fulfilled_quantity,
        comment: allocation.fulfillment_comment ?? '',
      },
    ]),
  ), [physical])
  const [values, setValues] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')
  const dirty = JSON.stringify(values) !== JSON.stringify(initial)

  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  async function save() {
    if (saving || !dirty) return
    setSaving(true)
    setMessage('')
    try {
      const updated = await saveSupplyFulfillment(
        request.id,
        line.id,
        request.version,
        physical.map((allocation) => ({
          allocation_id: allocation.id,
          fulfilled_quantity: values[allocation.id]?.quantity ?? '0',
          comment: values[allocation.id]?.comment.trim() || null,
        })),
      )
      onSaved(updated)
      setMessage('Факт сохранён')
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      setMessage(({
        SUPPLY_REQUEST_VERSION_CONFLICT:
          'Заявка изменилась. Обновите карточку.',
        SUPPLY_FULFILLMENT_EXCEEDS_PLANNED:
          'Отправленное количество не может превышать план.',
        SUPPLY_FULFILLMENT_DECREASE_COMMENT_REQUIRED:
          'При уменьшении факта обязателен комментарий.',
        SUPPLY_DEBT_INCLUSION_CONFIRMATION_REQUIRED:
          'Сначала подтвердите включение старого долга.',
      } as Record<string, string>)[code ?? ''] ?? 'Не удалось сохранить факт')
    } finally {
      setSaving(false)
    }
  }

  if (!physical.length) {
    return <p className="supply-complete">Физическая отправка не запланирована</p>
  }
  return (
    <div className="supply-fulfillment-editor">
      {physical.map((allocation) => (
        <div className="supply-fulfillment-row" key={allocation.id}>
          <strong>{allocation.action === 'TRANSFER' ? 'Перемещение' : 'Закупка'}</strong>
          <span>План: {allocation.planned_quantity}</span>
          <label>
            <span>Отправлено</span>
            <input
              type="number"
              min="0"
              max={allocation.planned_quantity}
              step="0.001"
              value={values[allocation.id]?.quantity ?? '0'}
              disabled={saving || request.status === 'FULFILLED'}
              onChange={(event) => setValues({
                ...values,
                [allocation.id]: {
                  ...values[allocation.id],
                  quantity: event.target.value,
                },
              })}
            />
          </label>
          <label>
            <span>Комментарий</span>
            <input
              value={values[allocation.id]?.comment ?? ''}
              disabled={saving || request.status === 'FULFILLED'}
              onChange={(event) => setValues({
                ...values,
                [allocation.id]: {
                  ...values[allocation.id],
                  comment: event.target.value,
                },
              })}
            />
          </label>
          <span>
            Осталось по allocation:{' '}
            {Math.max(
              Number(allocation.planned_quantity)
              - Number(values[allocation.id]?.quantity ?? 0),
              0,
            ).toFixed(3)}
          </span>
        </div>
      ))}
      <button
        type="button"
        disabled={saving || !dirty || request.status === 'FULFILLED'}
        onClick={() => void save()}
      >
        {saving ? 'Сохраняем…' : 'Сохранить факт'}
      </button>
      {message && <small>{message}</small>}
    </div>
  )
}

function SupplyRequestDetailPage() {
  const { requestId = '' } = useParams()
  const [request, setRequest] = useState<SupplyRequest | null>(null)
  const [products, setProducts] = useState<SupplyProduct[]>([])
  const [units, setUnits] = useState<SupplyUnit[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [mapping, setMapping] = useState<SupplyLineMappingState>({})
  const [working, setWorking] = useState<SupplyLineWorkingState>({})

  async function reload() {
    const item = await getSupplyRequest(requestId)
    setRequest(item)
    setState('ready')
  }

  useEffect(() => {
    Promise.all([getSupplyRequest(requestId), getSupplyProducts(), getSupplyUnits()])
      .then(([item, productPage, unitItems]) => {
        setRequest(item)
        setProducts(productPage.items)
        setUnits(unitItems.filter((unit) => unit.is_active))
        setState('ready')
      })
      .catch(() => setState('error'))
  }, [requestId])

  async function saveWorkingValues(
    line: SupplyLine,
    draft: ReturnType<typeof createSupplyLineWorkingDraft>,
  ) {
    if (
      !request || draft.status === 'loading' || !draft.workingName.trim()
      || Number(draft.quantity) <= 0 || !draft.unitId
    ) return
    setWorking((current) => updateSupplyLineWorkingDraft(
      current,
      line.id,
      draft,
      { status: 'loading', error: '' },
    ))
    setMessage('')
    try {
      const updated = await saveSupplyLineWorkingValues(
        request.id,
        line.id,
        {
          request_version: request.version,
          working_name: draft.workingName.trim(),
          requested_quantity: draft.quantity,
          requested_unit_id: draft.unitId,
        },
      )
      setRequest((current) => current && current.id === request.id
        ? {
            ...current,
            version: updated.request_version,
            lines: current.lines.map((item) => (
              item.id === line.id ? updated.line : item
            )),
          }
        : current)
      setWorking((current) => clearSupplyLineWorkingDraft(current, line.id))
      setMessage('Строка готова к планированию')
    } catch (error) {
      const errorMessage = error instanceof SupplyApiError
        && error.code === 'SUPPLY_REQUEST_VERSION_CONFLICT'
        ? 'Заявка изменилась. Обновите карточку и повторите.'
        : error instanceof SupplyApiError
        && ['SUPPLY_UNIT_NOT_FOUND', 'SUPPLY_UNIT_INACTIVE'].includes(error.code ?? '')
        ? 'Единица измерения больше недоступна. Выберите другую.'
        : 'Не удалось сохранить строку'
      setWorking((current) => updateSupplyLineWorkingDraft(
        current,
        line.id,
        draft,
        { status: 'error', error: errorMessage },
      ))
    }
  }

  async function mapLine(line: SupplyLine) {
    const draft = mapping[line.id]
    if (
      !request || busy || draft?.status === 'loading'
      || !draft?.productId || !draft.unitId || !draft.quantity
    ) return
    setMapping((current) => updateSupplyLineMappingDraft(
      current,
      line.id,
      draft,
      { status: 'loading', error: '' },
    ))
    setMessage('')
    let matched = false
    try {
      await matchSupplyLine(request.id, line.id, {
        expected_version: request.version,
        product_id: draft.productId,
        unit_id: draft.unitId,
        quantity: draft.quantity,
        save_alias: draft.saveAlias,
      })
      matched = true
      setMapping((current) => clearSupplyLineMappingDraft(current, line.id))
      await reload()
      setMessage(draft.saveAlias ? 'Строка сопоставлена, алиас сохранён' : 'Строка сопоставлена')
    } catch (error) {
      const errorMessage = matched
        ? 'Строка сопоставлена, но не удалось обновить карточку'
        : error instanceof SupplyApiError && error.code === 'SUPPLY_ALIAS_CONFLICT'
        ? 'Такое наименование уже связано с другим товаром'
        : 'Не удалось сопоставить строку. Обновите карточку и повторите.'
      if (matched) {
        setMessage(errorMessage)
      } else {
        setMapping((current) => updateSupplyLineMappingDraft(
          current,
          line.id,
          draft,
          { status: 'error', error: errorMessage },
        ))
      }
    }
  }

  async function plan() {
    if (!request || busy) return
    setBusy(true)
    try {
      setRequest(await planSupplyRequest(request.id, request.version))
      setMessage('Заявка переведена в план')
    } catch {
      setMessage('Заявку пока нельзя перевести в план')
    } finally {
      setBusy(false)
    }
  }

  async function cancel() {
    if (!request || busy) return
    const reason = window.prompt('Укажите причину отмены')
    if (!reason?.trim()) return
    setBusy(true)
    try {
      setRequest(await cancelSupplyRequest(request.id, request.version, reason.trim()))
      setMessage('Заявка отменена')
    } catch {
      setMessage('Не удалось отменить заявку')
    } finally {
      setBusy(false)
    }
  }

  async function fulfillAsPlanned() {
    if (!request || busy) return
    setBusy(true)
    setMessage('')
    try {
      setRequest(await fulfillSupplyAsPlanned(request.id, request.version))
      setMessage('Факт отправки сохранён по плану')
    } catch (error) {
      setMessage(
        error instanceof SupplyApiError
        && error.code === 'SUPPLY_DEBT_INCLUSION_CONFIRMATION_REQUIRED'
          ? 'Для одной из строк сначала подтвердите включение старого долга'
          : 'Не удалось сохранить факт по плану',
      )
    } finally {
      setBusy(false)
    }
  }

  async function confirmDebt(line: SupplyLine) {
    if (!request || busy) return
    const maximum = Math.min(
      Number(line.quantity ?? 0),
      Number(line.active_debt_quantity),
    )
    const entered = window.prompt(
      `Сколько старого долга включено в эту заявку? Максимум ${maximum}`,
      String(maximum),
    )
    if (entered === null || entered.trim() === '') return
    setBusy(true)
    try {
      setRequest(await confirmSupplyDebtInclusion(
        request.id, line.id, request.version, entered,
      ))
      setMessage('Включение долга подтверждено')
    } catch {
      setMessage('Не удалось подтвердить включение долга')
    } finally {
      setBusy(false)
    }
  }

  async function disableAlias(productId: string, aliasId: string) {
    if (busy) return
    setBusy(true)
    try {
      await disableSupplyAlias(productId, aliasId)
      const refreshed = await getSupplyProducts()
      setProducts(refreshed.items)
      setMessage('Алиас отключён')
    } catch {
      setMessage('Не удалось отключить алиас')
    } finally {
      setBusy(false)
    }
  }

  if (state === 'loading') return <p className="page-state">Загружаем заявку…</p>
  if (state === 'error' || !request) return <p className="request-message request-message-error">Заявка не найдена или недоступна</p>

  return (
    <section className="request-page request-detail-page supply-admin-page">
      <div className="request-panel">
        <div className="request-heading">
          <div><p className="eyebrow">СНАБЖЕНИЕ</p><h1>{request.public_number}</h1></div>
          <Link className="request-back-link" to="/supply/requests">← К реестру</Link>
        </div>
        <dl className="request-facts">
          <div><dt>Подразделение</dt><dd>{request.department.name}</dd></div>
          <div><dt>Направление</dt><dd>{request.direction.name}</dd></div>
          <div><dt>Цикл</dt><dd>{request.cycle?.cycle_date ?? '—'}</dd></div>
          <div><dt>Автор</dt><dd>{request.public_author_name ?? 'Сотрудник EOS'}</dd></div>
          <div><dt>Статус</dt><dd>{request.status}</dd></div>
          <div><dt>Создана / отправлена</dt><dd>{formatDate(request.created_at)} / {formatDate(request.submitted_at)}</dd></div>
          <div><dt>Версия</dt><dd>{request.version}</dd></div>
          <div><dt>Дубли</dt><dd>{request.duplicate_groups}</dd></div>
        </dl>
        <div className="supply-card-actions">
          <button type="button" disabled={!request.can_plan || busy} onClick={() => void plan()}>Перевести в план</button>
          <button
            type="button"
            disabled={request.status !== 'PLANNED' || busy}
            onClick={() => void fulfillAsPlanned()}
          >
            Отправить как запланировано
          </button>
          <button type="button" disabled={!['SUBMITTED', 'IN_REVIEW'].includes(request.status) || busy} onClick={() => void cancel()}>Отменить заявку</button>
          <button type="button" disabled={busy} onClick={() => void reload()}>Обновить</button>
          {message && <span>{message}</span>}
        </div>
        <div className="supply-lines">
          {request.lines.map((line) => {
            const draft = getSupplyLineMappingDraft(
              mapping,
              line.id,
              line.requested_unit?.id ?? line.parsed_unit?.id ?? '',
              line.quantity ?? line.parsed_quantity ?? '',
            )
            const workingFallback = createSupplyLineWorkingDraft(
              suggestSupplyWorkingName(line.parsed_name, line.raw_text),
              line.quantity ?? line.parsed_quantity ?? '',
              line.requested_unit?.id ?? line.parsed_unit?.id ?? '',
            )
            const workingDraft = getSupplyLineWorkingDraft(
              working,
              line.id,
              workingFallback,
            )
            const updateDraft = (
              changes: Parameters<typeof updateSupplyLineMappingDraft>[3],
            ) => setMapping((current) => updateSupplyLineMappingDraft(
              current,
              line.id,
              draft,
              changes,
            ))
            return (
              <article className="supply-line-card" key={line.id}>
                <header>
                  <div>
                    <strong>{line.working_name}</strong>
                    <span>{line.quantity ?? line.parsed_quantity ?? '—'} {line.requested_unit?.short_name_ru ?? line.parsed_unit?.short_name_ru ?? ''}</span>
                  </div>
                  <small>
                    {line.product_id ? 'Позиция сопоставлена' : 'Позиция не сопоставлена'}
                    {' · '}дубли: {line.duplicate_status}
                  </small>
                </header>
                <details><summary>Исходная строка</summary><p>{line.raw_text}</p></details>
                {(!line.quantity || !line.requested_unit)
                  && ['SUBMITTED', 'IN_REVIEW'].includes(request.status) && (
                  <div className="supply-mapping">
                    <h3>Уточните строку</h3>
                    <label>
                      <span>Рабочее название</span>
                      <input
                        value={workingDraft.workingName}
                        disabled={workingDraft.status === 'loading'}
                        onChange={(event) => setWorking((current) => (
                          updateSupplyLineWorkingDraft(
                            current,
                            line.id,
                            workingDraft,
                            {
                              workingName: event.target.value,
                              status: 'idle',
                              error: '',
                            },
                          )
                        ))}
                      />
                    </label>
                    <label>
                      <span>Количество</span>
                      <input
                        type="number"
                        min="0.001"
                        step="0.001"
                        value={workingDraft.quantity}
                        disabled={workingDraft.status === 'loading'}
                        onChange={(event) => setWorking((current) => (
                          updateSupplyLineWorkingDraft(
                            current,
                            line.id,
                            workingDraft,
                            {
                              quantity: event.target.value,
                              status: 'idle',
                              error: '',
                            },
                          )
                        ))}
                      />
                    </label>
                    <label>
                      <span>Единица измерения</span>
                      <select
                        value={workingDraft.unitId}
                        disabled={workingDraft.status === 'loading'}
                        onChange={(event) => setWorking((current) => (
                          updateSupplyLineWorkingDraft(
                            current,
                            line.id,
                            workingDraft,
                            {
                              unitId: event.target.value,
                              status: 'idle',
                              error: '',
                            },
                          )
                        ))}
                      >
                        <option value="">Выберите единицу</option>
                        {units.map((unit) => (
                          <option key={unit.id} value={unit.id}>
                            {unit.name_ru} ({unit.short_name_ru})
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      disabled={
                        workingDraft.status === 'loading'
                        || !workingDraft.workingName.trim()
                        || Number(workingDraft.quantity) <= 0
                        || !workingDraft.unitId
                      }
                      onClick={() => void saveWorkingValues(line, workingDraft)}
                    >
                      {workingDraft.status === 'loading'
                        ? 'Сохраняем…'
                        : 'Сохранить строку'}
                    </button>
                    {workingDraft.error && (
                      <small className="request-message-error">
                        {workingDraft.error}
                      </small>
                    )}
                  </div>
                )}
                {line.match_status === 'NEEDS_REVIEW' && (
                  <details className="supply-mapping">
                    <summary>Сопоставить с iiko позже</summary>
                    <p className="request-message request-message-warning">
                      {line.quantity && line.requested_unit
                        ? 'Позиция не сопоставлена. Планирование и факт доступны по рабочему наименованию.'
                        : 'Сначала уточните рабочее название, количество и единицу.'}
                    </p>
                    <p>Разбор: {line.parsed_name ?? 'название не распознано'} · {line.parsed_quantity ?? '—'} {line.parsed_unit?.short_name_ru ?? 'единица не распознана'}</p>
                    <label><span>Поиск товара</span><input value={draft.searchQuery} onChange={(event) => updateDraft({ searchQuery: event.target.value, error: '', status: 'idle' })} /></label>
                    <label><span>Активный товар</span>
                      <select value={draft.productId} disabled={busy || draft.status === 'loading'} onChange={(event) => {
                        const product = products.find((item) => item.id === event.target.value)
                        updateDraft({
                          productId: event.target.value,
                          unitId: line.requested_unit?.id
                            ?? product?.default_unit.id
                            ?? draft.unitId,
                          error: '',
                          status: 'idle',
                        })
                      }}>
                        <option value="">Выберите товар</option>
                        {products.filter((product) => product.name.toLocaleLowerCase('ru-RU').includes(draft.searchQuery.trim().toLocaleLowerCase('ru-RU'))).map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
                      </select>
                    </label>
                    <label><span>Количество</span><input type="number" min="0.001" step="0.001" value={draft.quantity} disabled={draft.status === 'loading'} onChange={(event) => updateDraft({ quantity: event.target.value, error: '', status: 'idle' })} /></label>
                    <label><input type="checkbox" checked={draft.saveAlias} disabled={draft.status === 'loading'} onChange={(event) => updateDraft({ saveAlias: event.target.checked, error: '', status: 'idle' })} /> Запомнить это наименование</label>
                    <button type="button" disabled={busy || draft.status === 'loading' || !draft.productId || !draft.unitId || !draft.quantity} onClick={() => void mapLine(line)}>
                      {draft.status === 'loading' ? 'Сопоставляем…' : 'Сопоставить'}
                    </button>
                    {draft.error && <small className="request-message-error">{draft.error}</small>}
                    {draft.productId && (
                      <div className="supply-aliases">
                        <span>Сохранённые алиасы:</span>
                        {products.find((product) => product.id === draft.productId)?.aliases
                          .filter((alias) => alias.status === 'APPROVED')
                          .map((alias) => (
                            <button key={alias.id} type="button" disabled={busy} onClick={() => void disableAlias(draft.productId, alias.id)}>
                              {alias.alias} · отключить
                            </button>
                          ))}
                      </div>
                    )}
                  </details>
                )}
                {line.quantity && line.requested_unit
                  && ['MATCHED', 'NEEDS_REVIEW'].includes(line.match_status)
                  && ['SUBMITTED', 'IN_REVIEW'].includes(request.status) && (
                  <AllocationEditor request={request} line={line} onSaved={setRequest} />
                )}
                {['PLANNED', 'PARTIALLY_FULFILLED', 'FULFILLED'].includes(request.status) && (
                  <div className="supply-fulfillment">
                    <dl className="supply-line-totals">
                      <div><dt>Запросили</dt><dd>{line.quantity ?? '—'}</dd></div>
                      <div><dt>Перемещение, план</dt><dd>{line.planned_transfer}</dd></div>
                      <div><dt>Закупка, план</dt><dd>{line.planned_purchase}</dd></div>
                      <div><dt>Отмена</dt><dd>{line.planned_cancel}</dd></div>
                      <div><dt>Отправлено</dt><dd>{line.fulfilled_total}</dd></div>
                      <div><dt>Осталось</dt><dd>{line.unresolved_quantity}</dd></div>
                      <div><dt>Активный долг</dt><dd>{line.active_debt_quantity}</dd></div>
                      <div><dt>Включено старого долга</dt><dd>{line.debt_quantity_included}</dd></div>
                    </dl>
                    {line.requires_debt_confirmation && request.status !== 'FULFILLED' && (
                      <div className="request-message request-message-warning">
                        Новая заявка меньше активного долга. Подтвердите,
                        какая часть долга включена.
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void confirmDebt(line)}
                        >
                          Подтвердить включение
                        </button>
                      </div>
                    )}
                    {line.active_debt_id && (
                      <Link to={`/supply/debts?open=${line.active_debt_id}`}>
                        Открыть долг
                      </Link>
                    )}
                    <FulfillmentEditor
                      request={request}
                      line={line}
                      onSaved={setRequest}
                    />
                  </div>
                )}
              </article>
            )
          })}
        </div>
      </div>
    </section>
  )
}

export default SupplyRequestDetailPage
