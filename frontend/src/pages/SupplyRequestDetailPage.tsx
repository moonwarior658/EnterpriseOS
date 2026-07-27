import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  cancelSupplyRequest,
  disableSupplyAlias,
  getSupplyProducts,
  getSupplyRequest,
  matchSupplyLine,
  planSupplyRequest,
  saveSupplyAllocations,
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
              </article>
            )
          })}
        </div>
      </div>
    </section>
  )
}

export default SupplyRequestDetailPage
