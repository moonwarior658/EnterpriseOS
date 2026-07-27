import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  cancelSupplyRequest,
  disableSupplyAlias,
  confirmSupplyDebtInclusion,
  fulfillSupplyAsPlanned,
  getSupplyProducts,
  getSupplyRequest,
  matchSupplyLine,
  planSupplyRequest,
  saveSupplyAllocations,
  saveSupplyFulfillment,
  SupplyApiError,
  type SupplyLine,
  type SupplyProduct,
  type SupplyRequest,
} from '../services/supplyAdmin'

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
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [productSearch, setProductSearch] = useState('')
  const [mapping, setMapping] = useState<Record<string, {
    productId: string; unitId: string; quantity: string; saveAlias: boolean
  }>>({})

  async function reload() {
    const item = await getSupplyRequest(requestId)
    setRequest(item)
    setState('ready')
  }

  useEffect(() => {
    Promise.all([getSupplyRequest(requestId), getSupplyProducts()])
      .then(([item, productPage]) => {
        setRequest(item)
        setProducts(productPage.items)
        setState('ready')
      })
      .catch(() => setState('error'))
  }, [requestId])

  async function mapLine(line: SupplyLine) {
    if (!request) return
    const draft = mapping[line.id]
    if (!draft?.productId || !draft.unitId || !draft.quantity) return
    setBusy(true)
    setMessage('')
    try {
      await matchSupplyLine(request.id, line.id, {
        expected_version: request.version,
        product_id: draft.productId,
        unit_id: draft.unitId,
        quantity: draft.quantity,
        save_alias: draft.saveAlias,
      })
      await reload()
      setMessage(draft.saveAlias ? 'Строка сопоставлена, алиас сохранён' : 'Строка сопоставлена')
    } catch (error) {
      setMessage(error instanceof SupplyApiError && error.code === 'SUPPLY_ALIAS_CONFLICT'
        ? 'Такое наименование уже связано с другим товаром'
        : 'Не удалось сопоставить строку. Обновите карточку и повторите.')
    } finally {
      setBusy(false)
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
            const draft = mapping[line.id] ?? {
              productId: '', unitId: line.parsed_unit?.id ?? '',
              quantity: line.parsed_quantity ?? '', saveAlias: false,
            }
            return (
              <article className="supply-line-card" key={line.id}>
                <header>
                  <div>
                    <strong>{line.product?.name ?? line.parsed_name ?? 'Неизвестная позиция'}</strong>
                    <span>{line.quantity ?? line.parsed_quantity ?? '—'} {line.requested_unit?.short_name_ru ?? line.parsed_unit?.short_name_ru ?? ''}</span>
                  </div>
                  <small>{line.match_status} · {line.match_method ?? 'без источника'} · дубли: {line.duplicate_status}</small>
                </header>
                <details><summary>Исходная строка</summary><p>{line.raw_text}</p></details>
                {line.match_status === 'NEEDS_REVIEW' && (
                  <div className="supply-mapping">
                    <p>Разбор: {line.parsed_name ?? 'название не распознано'} · {line.parsed_quantity ?? '—'} {line.parsed_unit?.short_name_ru ?? 'единица не распознана'}</p>
                    <label><span>Поиск товара</span><input value={productSearch} onChange={(event) => setProductSearch(event.target.value)} /></label>
                    <label><span>Активный товар</span>
                      <select value={draft.productId} disabled={busy} onChange={(event) => {
                        const product = products.find((item) => item.id === event.target.value)
                        setMapping({ ...mapping, [line.id]: { ...draft, productId: event.target.value, unitId: product?.default_unit.id ?? draft.unitId } })
                      }}>
                        <option value="">Выберите товар</option>
                        {products.filter((product) => product.name.toLocaleLowerCase('ru-RU').includes(productSearch.trim().toLocaleLowerCase('ru-RU'))).map((product) => <option key={product.id} value={product.id}>{product.name}</option>)}
                      </select>
                    </label>
                    <label><span>Количество</span><input type="number" min="0.001" step="0.001" value={draft.quantity} onChange={(event) => setMapping({ ...mapping, [line.id]: { ...draft, quantity: event.target.value } })} /></label>
                    <label><input type="checkbox" checked={draft.saveAlias} onChange={(event) => setMapping({ ...mapping, [line.id]: { ...draft, saveAlias: event.target.checked } })} /> Запомнить это наименование</label>
                    <button type="button" disabled={busy || !draft.productId || !draft.unitId || !draft.quantity} onClick={() => void mapLine(line)}>Сопоставить</button>
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
                  </div>
                )}
                {line.match_status === 'MATCHED' && (
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
