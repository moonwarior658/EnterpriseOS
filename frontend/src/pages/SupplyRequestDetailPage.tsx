import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EosSelect } from '../components/EosFormControls'
import { useAuth } from '../contexts/AuthContext'
import {
  cancelSupplyRequest,
  assignSupplyProductSource,
  bootstrapSupplyProductSources,
  calculateSupplyStock,
  confirmSupplyDebtInclusion,
  confirmSupplyStockCalculation,
  fulfillSupplyAsPlanned,
  getSupplyProductSourcePreview,
  getSupplyIikoDocuments,
  getSupplyPrintJobs,
  getSupplyStockCalculation,
  getSupplyProducts,
  getSupplyRequest,
  getSupplyUnits,
  matchSupplyLine,
  openSupplyIikoDocumentPdf,
  printSupplyRequest,
  reprintSupplyRequest,
  confirmSupplyContextMapping,
  planSupplyRequest,
  recognizeSupplyRequest,
  reparseSupplyLine,
  saveSupplyFulfillment,
  saveSupplyLineWorkingValues,
  updateSupplyStockTransferable,
  SupplyApiError,
  type SupplyLine,
  type SupplyIikoDocument,
  type SupplyPrintJob,
  type SupplyProductSourcePreview,
  type SupplyProduct,
  type SupplyRequest,
  type SupplyStockCalculation,
  type SupplyUnit,
} from '../services/supplyAdmin'
import {
  clearSupplyLineMappingDraft,
  clearSupplyLineWorkingDraft,
  findNormalSupplyPrintJob,
  formatSupplyQuantityMillis,
  getSupplyLineMappingDraft,
  getSupplyLineWorkingDraft,
  isSupplyLineWorkingDraftDirty,
  isSupplyLineMatchReady,
  nextSupplyLineToMatch,
  requiresSupplyLineMatch,
  saveDirtySupplyLines,
  supplyExpectedDebtMillis,
  supplyLineWorkingBaseline,
  supplyMatchProgress,
  supplyPrintPurposeLabel,
  supplyPrintStatusLabel,
  supplyQuantityMillis,
  supplySendExcessMillis,
  updateSupplyLineMappingDraft,
  updateSupplyLineWorkingDraft,
  suggestSupplyWorkingName,
  type SupplyLineMappingDraft,
  type SupplyLineMappingState,
  type SupplyLineWorkingDraft,
  type SupplyLineWorkingState,
} from './supplyRequestDetailLogic'

function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'long',
    timeStyle: 'short',
  }).format(new Date(value))
}

function statusLabel(value: SupplyRequest['status']): string {
  return ({
    DRAFT: 'Черновик',
    SUBMITTED: 'Отправлена',
    IN_REVIEW: 'В обработке',
    PLANNED: 'В работе',
    PARTIALLY_FULFILLED: 'Исполнена частично',
    FULFILLED: 'Исполнена',
    CANCELLED: 'Отменена',
  } as const)[value]
}

function workingSaveError(error: unknown): string {
  if (
    error instanceof SupplyApiError
    && error.code === 'SUPPLY_REQUEST_VERSION_CONFLICT'
  ) {
    return 'Заявка изменилась. Обновите карточку и повторите.'
  }
  if (
    error instanceof SupplyApiError
    && ['SUPPLY_UNIT_NOT_FOUND', 'SUPPLY_UNIT_INACTIVE'].includes(
      error.code ?? '',
    )
  ) {
    return 'Единица больше недоступна. Выберите другую.'
  }
  return 'Не удалось сохранить эту строку.'
}

function SupplyLineMappingEditor({
  line,
  draft,
  workingDraft,
  units,
  disabled,
  onChange,
  onMatch,
  onReparse,
  inputRef,
}: {
  line: SupplyLine
  draft: SupplyLineMappingDraft
  workingDraft: SupplyLineWorkingDraft
  units: SupplyUnit[]
  disabled: boolean
  onChange: (changes: Partial<SupplyLineMappingDraft>) => void
  onMatch: () => void
  onReparse: () => void
  inputRef: (element: HTMLInputElement | null) => void
}) {
  const [searchResult, setSearchResult] = useState<{
    query: string
    items: SupplyProduct[]
    state: 'idle' | 'loading' | 'error'
  }>({ query: '', items: [], state: 'idle' })
  const currentQuery = draft.searchQuery.trim()
  const currentResult = searchResult.query === currentQuery
    ? searchResult
    : { query: currentQuery, items: [], state: 'idle' as const }
  const currentUnit = units.find((unit) => unit.id === workingDraft.unitId)
  const matchReady = isSupplyLineMatchReady(draft, workingDraft, units)

  useEffect(() => {
    const query = draft.searchQuery.trim()
    if (!query) return

    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      setSearchResult({ query, items: [], state: 'loading' })
      getSupplyProducts(query, controller.signal).then((page) => {
        if (controller.signal.aborted) return
        setSearchResult({
          query,
          items: page.items.slice(0, 20),
          state: 'idle',
        })
      }).catch(() => {
        if (!controller.signal.aborted) {
          setSearchResult({ query, items: [], state: 'error' })
        }
      })
    }, 300)
    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [draft.searchQuery, line.id])

  return (
    <div className="supply-line-mapping-workspace">
      <div className="supply-source-line">
        <span>Исходная строка</span>
        <strong>{line.raw_text}</strong>
      </div>
      <div className="supply-product-autocomplete">
        <label htmlFor={`supply-product-search-${line.id}`}>
          Товар EOS
        </label>
        <input
          id={`supply-product-search-${line.id}`}
          ref={inputRef}
          aria-label={`Поиск товара EOS, строка ${line.position}`}
          autoComplete="off"
          placeholder="Начните вводить название"
          value={draft.searchQuery}
          disabled={disabled}
          onChange={(event) => onChange({
            searchQuery: event.target.value,
            productId: '',
            selectedProduct: null,
            status: 'idle',
            error: '',
          })}
        />
        {currentResult.state === 'loading' && <small>Ищем товары…</small>}
        {currentResult.state === 'error' && (
          <small className="request-message-error">
            Не удалось загрузить предложения.
          </small>
        )}
        {currentResult.items.length > 0 && (
          <div className="supply-product-suggestions" role="listbox">
            {currentResult.items.map((product) => (
              <button
                type="button"
                role="option"
                aria-selected={draft.productId === product.id}
                key={product.id}
                onClick={() => {
                  onChange({
                    productId: product.id,
                    selectedProduct: product,
                    status: 'idle',
                    error: '',
                  })
                  setSearchResult({ query: '', items: [], state: 'idle' })
                }}
              >
                <strong>{product.name}</strong>
                <span>{product.default_unit.short_name_ru}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {draft.selectedProduct && (
        <div className="supply-selected-product" role="status">
          <span>Выбран товар EOS</span>
          <strong>{draft.selectedProduct.name}</strong>
          <small>
            Базовая единица: {draft.selectedProduct.default_unit.short_name_ru}
          </small>
        </div>
      )}
      <div className="supply-mapping-values">
        <span>Количество: <strong>{workingDraft.quantity || '—'}</strong></span>
        <span>
          Единица:{' '}
          <strong>
            {currentUnit?.short_name_ru ?? 'не определена'}
          </strong>
        </span>
      </div>
      {line.match_status === 'NEEDS_REVIEW' && (
        <button
          type="button"
          disabled={disabled || draft.status === 'loading'}
          onClick={onReparse}
        >
          Перераспознать строку
        </button>
      )}
      <button
        className="supply-map-product-button"
        type="button"
        disabled={
          disabled || draft.status === 'loading' || !matchReady
        }
        onClick={onMatch}
      >
        {draft.status === 'loading'
          ? 'Сопоставляем…'
          : 'Сопоставить с товаром EOS'}
      </button>
      {draft.error && (
        <small className="request-message-error">{draft.error}</small>
      )}
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
  const invalid = Object.values(values).some(
    (value) => supplyQuantityMillis(value.quantity) === null,
  )

  useEffect(() => {
    if (!dirty) return
    const handler = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [dirty])

  async function save() {
    if (saving || !dirty || invalid) return
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
          'Не удалось сохранить фактически отправленное количество.',
        SUPPLY_FULFILLMENT_DECREASE_COMMENT_REQUIRED:
          'При уменьшении факта обязателен комментарий.',
        SUPPLY_DEBT_INCLUSION_CONFIRMATION_REQUIRED:
          'Сначала подтвердите включение старого долга.',
        SUPPLY_DEBT_PRODUCT_REQUIRED:
          'Сначала сопоставьте строку с товаром EOS.',
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
          <strong>
            {allocation.action === 'TRANSFER' ? 'Перемещение' : 'Закупка'}
          </strong>
          <span>План: {allocation.planned_quantity}</span>
          <label>
            <span>Отправлено</span>
            <input
              type="number"
              min="0"
              step="0.001"
              value={values[allocation.id]?.quantity ?? '0'}
              disabled={saving || request.status !== 'PLANNED'}
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
              disabled={saving || request.status !== 'PLANNED'}
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
            Осталось:{' '}
            {formatSupplyQuantityMillis(Math.max(
              (supplyQuantityMillis(allocation.planned_quantity) ?? 0)
              - (supplyQuantityMillis(
                values[allocation.id]?.quantity ?? '',
              ) ?? 0),
              0,
            ))}
          </span>
        </div>
      ))}
      <button
        type="button"
        disabled={
          saving || !dirty || invalid || request.status !== 'PLANNED'
        }
        onClick={() => void save()}
      >
        {saving ? 'Сохраняем…' : 'Сохранить факт'}
      </button>
      {invalid && <small>Введите количество с точностью до трёх знаков</small>}
      {message && <small>{message}</small>}
    </div>
  )
}

function SupplyExcessFact({ line }: { line: SupplyLine }) {
  const excess = supplySendExcessMillis(
    line.quantity ?? '',
    line.fulfilled_total,
  )
  if (excess === null || excess <= 0) return null
  return (
    <div>
      <dt>Сверх заявки</dt>
      <dd>{formatSupplyQuantityMillis(excess)}</dd>
    </div>
  )
}

function SupplyRequestReadOnlyCard({
  request,
}: {
  request: SupplyRequest
}) {
  return (
    <section className="request-page request-detail-page supply-admin-page">
      <div className="request-panel">
        <div className="request-heading supply-simple-heading">
          <div>
            <p className="eyebrow">СНАБЖЕНИЕ · ТОЛЬКО ПРОСМОТР</p>
            <h1>{request.public_number}</h1>
            <p>
              {request.department.name} · {request.direction.name}
              {' · '}{statusLabel(request.status)}
            </p>
          </div>
          <Link className="request-back-link" to="/supply/requests">
            ← К реестру
          </Link>
        </div>

        <dl className="request-facts">
          <div><dt>Автор</dt><dd>{request.public_author_name ?? 'Не указано'}</dd></div>
          <div><dt>Создана</dt><dd>{formatDate(request.created_at)}</dd></div>
          <div><dt>Отправлена</dt><dd>{formatDate(request.submitted_at)}</dd></div>
          <div><dt>Статус</dt><dd>{statusLabel(request.status)}</dd></div>
        </dl>

        <div className="supply-simple-table" role="table">
          <div className="supply-simple-table-head" role="row">
            <span role="columnheader">Название</span>
            <span role="columnheader">Количество</span>
            <span role="columnheader">Единица</span>
            <span aria-hidden="true" />
          </div>
          {request.lines.map((line) => (
            <div className="supply-simple-line" role="row" key={line.id}>
              <span role="cell">{line.working_name || line.raw_text}</span>
              <span role="cell">
                {['PARTIALLY_FULFILLED', 'FULFILLED'].includes(request.status)
                  ? line.fulfilled_total
                  : line.send_quantity ?? line.quantity ?? '—'}
              </span>
              <span role="cell">
                {line.requested_unit?.short_name_ru
                  ?? line.parsed_unit?.short_name_ru
                  ?? '—'}
              </span>
              <span role="cell" aria-hidden="true" />
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

function SupplyRequestDetailPage() {
  const { user } = useAuth()
  const readOnly = !user?.is_admin
  const { requestId = '' } = useParams()
  const [request, setRequest] = useState<SupplyRequest | null>(null)
  const [units, setUnits] = useState<SupplyUnit[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const primaryActionInFlight = useRef(false)
  const recognitionAttempts = useRef(new Set<string>())
  const mappingInputRefs = useRef(new Map<string, HTMLInputElement>())
  const [mapping, setMapping] = useState<SupplyLineMappingState>({})
  const [working, setWorking] = useState<SupplyLineWorkingState>({})
  const [fulfillment, setFulfillment] = useState<Record<string, string>>({})
  const [sourcePreview, setSourcePreview] = useState<SupplyProductSourcePreview | null>(null)
  const [iikoDocuments, setIikoDocuments] = useState<SupplyIikoDocument[]>([])
  const [printJobs, setPrintJobs] = useState<SupplyPrintJob[]>([])
  const [printJobsState, setPrintJobsState] = useState<
    'loading' | 'ready' | 'error'
  >('loading')
  const [sourceState, setSourceState] = useState<'loading' | 'ready' | 'error'>(
    'loading',
  )
  const [stockCalculation, setStockCalculation] = useState<SupplyStockCalculation | null>(null)
  const [stockCalculationState, setStockCalculationState] = useState<
    'loading' | 'ready' | 'error'
  >('loading')
  const [stockDrafts, setStockDrafts] = useState<Record<string, string>>({})

  const editable = request
    ? ['SUBMITTED', 'IN_REVIEW'].includes(request.status)
    : false
  const dirtyIds = useMemo(() => request?.lines
    .filter((line) => {
      const draft = working[line.id]
      return draft && isSupplyLineWorkingDraftDirty(
        draft,
        supplyLineWorkingBaseline(line),
      )
    })
    .map((line) => line.id) ?? [], [request, working])
  const dirtySet = useMemo(() => new Set(dirtyIds), [dirtyIds])
  const hasDirty = dirtyIds.length > 0
  const hasFulfillmentDraft = Object.keys(fulfillment).length > 0
  const invalidDirty = request?.lines.some((line) => {
    if (!dirtySet.has(line.id)) return false
    const draft = working[line.id]
    const quantity = supplyQuantityMillis(draft?.quantity ?? '')
    return !draft?.workingName.trim()
      || quantity === null
      || quantity < 0
      || !draft.unitId
  }) ?? false
  const readyToSend = request?.lines.length
    && request.lines.every((line) => (
      ['MATCHED', 'NEEDS_REVIEW'].includes(line.match_status)
      && line.quantity
      && line.requested_unit
      && !line.requires_debt_confirmation
      && !['SUSPECTED', 'CONFIRMED'].includes(line.duplicate_status)
    ))
  const invalidFulfillment = request?.status === 'PLANNED'
    && request.lines.some((line) => {
      const fulfilled = supplyQuantityMillis(fulfillment[line.id] ?? '0')
      const approved = supplyQuantityMillis(line.quantity ?? '')
      return fulfilled === null
        || approved === null
        || (!line.requested_unit?.allows_fraction && fulfilled % 1000 !== 0)
    })
  const matchProgress = useMemo(
    () => supplyMatchProgress(request?.lines ?? []),
    [request],
  )
  const hasStockDraft = stockCalculation?.groups.some((group) => (
    group.lines.some((line) => line.transferable_quantity !== null
      && stockDrafts[line.id] !== line.transferable_quantity)
  )) ?? false
  const hasBlockedStock = stockCalculation?.groups.some((group) => (
    group.lines.some((line) => line.unavailable_reason !== null)
  )) ?? false
  const printableIikoDocuments = useMemo(
    () => iikoDocuments.filter((document) => document.printable),
    [iikoDocuments],
  )
  const normalPrintJob = useMemo(
    () => findNormalSupplyPrintJob(printJobs),
    [printJobs],
  )

  async function reload(): Promise<SupplyRequest> {
    const item = await getSupplyRequest(requestId)
    setRequest(item)
    setFulfillment({})
    setState('ready')
    return item
  }

  async function reloadIikoDocuments(): Promise<SupplyIikoDocument[]> {
    const documents = await getSupplyIikoDocuments(requestId)
    setIikoDocuments(documents)
    return documents
  }

  async function reloadPrintJobs(): Promise<SupplyPrintJob[]> {
    const jobs = await getSupplyPrintJobs(requestId)
    setPrintJobs(jobs)
    setPrintJobsState('ready')
    return jobs
  }

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      setState('loading')
      setRequest(null)
      setMapping({})
      setWorking({})
      setFulfillment({})
      void (async () => {
        try {
          if (readOnly) {
            const item = await getSupplyRequest(requestId, controller.signal)
            if (controller.signal.aborted) return
            setRequest(item)
            setState('ready')
            return
          }
          const [loadedRequest, unitItems] = await Promise.all([
            getSupplyRequest(requestId, controller.signal),
            getSupplyUnits(controller.signal),
          ])
          let item = loadedRequest
          const recognitionKey = `${item.id}:${item.version}`
          if (
            item.lines.some((line) => line.match_status === 'UNPROCESSED')
            && !recognitionAttempts.current.has(recognitionKey)
          ) {
            recognitionAttempts.current.add(recognitionKey)
            try {
              await recognizeSupplyRequest(
                item.id,
                item.version,
                controller.signal,
              )
              item = await getSupplyRequest(requestId, controller.signal)
            } catch {
              if (!controller.signal.aborted) {
                setMessage('Не удалось автоматически распознать строки.')
              }
            }
          }
          if (controller.signal.aborted) return
          setRequest(item)
          setUnits(unitItems.filter((unit) => unit.is_active))
          setState('ready')
        } catch {
          if (!controller.signal.aborted) setState('error')
        }
      })()
    }, 0)
    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [readOnly, requestId])

  useEffect(() => {
    const controller = new AbortController()
    void getSupplyIikoDocuments(requestId, controller.signal)
      .then((documents) => {
        if (!controller.signal.aborted) setIikoDocuments(documents)
      })
      .catch(() => {
        if (!controller.signal.aborted) setIikoDocuments([])
      })
    return () => controller.abort()
  }, [requestId])

  useEffect(() => {
    if (!printJobs.some((job) => (
      job.status === 'QUEUED_FOR_PRINT' || job.status === 'PRINTING'
    ))) return
    const interval = window.setInterval(() => {
      void getSupplyPrintJobs(requestId)
        .then(setPrintJobs)
        .catch(() => undefined)
    }, 5_000)
    return () => window.clearInterval(interval)
  }, [printJobs, requestId])

  useEffect(() => {
    const controller = new AbortController()
    const loadingTimeout = window.setTimeout(() => {
      if (!controller.signal.aborted) setPrintJobsState('loading')
    }, 0)
    void getSupplyPrintJobs(requestId, controller.signal)
      .then((jobs) => {
        if (!controller.signal.aborted) {
          setPrintJobs(jobs)
          setPrintJobsState('ready')
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setPrintJobs([])
          setPrintJobsState('error')
        }
      })
    return () => {
      window.clearTimeout(loadingTimeout)
      controller.abort()
    }
  }, [requestId])

  useEffect(() => {
    if (!request || readOnly) return
    const controller = new AbortController()
    Promise.all([
      getSupplyProductSourcePreview(request.id, controller.signal),
      getSupplyStockCalculation(request.id, controller.signal),
    ]).then(([preview, calculation]) => {
      if (controller.signal.aborted) return
      setSourcePreview(preview)
      setSourceState('ready')
      setStockCalculation(calculation)
      setStockDrafts(Object.fromEntries(
        calculation?.groups.flatMap((group) => group.lines)
          .filter((line) => line.transferable_quantity !== null)
          .map((line) => [line.id, line.transferable_quantity as string]) ?? [],
      ))
      setStockCalculationState('ready')
    }).catch(() => {
      if (!controller.signal.aborted) {
        setSourceState('error')
        setStockCalculationState('error')
      }
    })
    return () => controller.abort()
  }, [readOnly, request])

  useEffect(() => {
    if (!hasDirty && !hasFulfillmentDraft) return
    const handler = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [hasDirty, hasFulfillmentDraft])

  function changeWorking(
    line: SupplyLine,
    draft: SupplyLineWorkingDraft,
    changes: Partial<SupplyLineWorkingDraft>,
  ) {
    setWorking((current) => updateSupplyLineWorkingDraft(
      current,
      line.id,
      draft,
      { ...changes, status: 'idle', error: '' },
    ))
  }

  async function saveAllWorkingValues() {
    if (
      !request || busy || primaryActionInFlight.current
      || !hasDirty || invalidDirty
    ) return
    primaryActionInFlight.current = true
    setBusy(true)
    setMessage('')
    setWorking((current) => {
      const next = { ...current }
      dirtyIds.forEach((lineId) => {
        if (next[lineId]) {
          next[lineId] = { ...next[lineId], status: 'loading', error: '' }
        }
      })
      return next
    })
    try {
      const result = await saveDirtySupplyLines(
        request.id,
        request.version,
        request.lines,
        working,
        saveSupplyLineWorkingValues,
      )
      let remaining = result.remaining
      Object.entries(result.errors).forEach(([lineId, error]) => {
        const draft = remaining[lineId]
        if (draft) {
          remaining = {
            ...remaining,
            [lineId]: {
              ...draft,
              status: 'error',
              error: workingSaveError(error),
            },
          }
        }
      })
      setWorking(remaining)
      setRequest((current) => current && current.id === request.id
        ? {
            ...current,
            version: result.requestVersion,
            lines: current.lines.map(
              (line) => result.savedLines[line.id] ?? line,
            ),
          }
        : current)
      const failedCount = Object.keys(result.errors).length
      setMessage(failedCount
        ? `Часть изменений не сохранена: ${failedCount}`
        : 'Все изменения сохранены')
    } finally {
      primaryActionInFlight.current = false
      setBusy(false)
    }
  }

  async function sendToWork() {
    if (
      !request || busy || primaryActionInFlight.current
      || hasDirty || !readyToSend
    ) return
    primaryActionInFlight.current = true
    setBusy(true)
    setMessage('')
    try {
      setRequest(await planSupplyRequest(request.id, request.version, true))
      const documents = await reloadIikoDocuments()
      if (documents.some((document) => document.status === 'UNKNOWN')) {
        setMessage('Заявка отправлена в работу. Требуется проверка в iiko')
      } else if (documents.some((document) => document.status === 'FAILED')) {
        setMessage('Заявка отправлена в работу. Документ iiko не создан')
      } else {
        setMessage('Заявка отправлена в работу')
      }
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      setMessage(({
        SUPPLY_REQUEST_VERSION_CONFLICT:
          'Заявка изменилась. Обновите карточку и повторите.',
        SUPPLY_DUPLICATES_PRESENT:
          'Сначала устраните отмеченные дубли.',
        SUPPLY_REQUEST_PLANNING_INCOMPLETE:
          'Проверьте название, количество и фасовку каждой строки.',
        SUPPLY_SEND_QUANTITY_INVALID:
          'Для этой единицы разрешено только целое количество.',
        SUPPLY_INTERNAL_TRANSFER_DOCUMENT_WRITE_UNSUPPORTED:
          'Создание внутреннего перемещения iiko пока не поддерживается.',
        SUPPLY_IIKO_DOCUMENT_PREPARATION_INCOMPLETE:
          'Не удалось подготовить документы iiko: проверьте mapping товара, единицы и SOURCE.',
        SUPPLY_IIKO_DOCUMENT_SOURCE_MISMATCH:
          'SOURCE не соответствует подтверждённому маршруту документа iiko.',
      } as Record<string, string>)[code ?? '']
        ?? 'Не удалось отправить заявку в работу')
    } finally {
      primaryActionInFlight.current = false
      setBusy(false)
    }
  }

  async function downloadIikoPdf(documentWriteId?: string) {
    setMessage('')
    try {
      await openSupplyIikoDocumentPdf(requestId, documentWriteId)
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      setMessage(({
        SUPPLY_IIKO_DOCUMENT_NOT_VERIFIED:
          'Документ ещё не подтверждён по данным iiko.',
        SUPPLY_IIKO_DOCUMENT_READBACK_NOT_FOUND:
          'Документ не найден при повторном чтении iiko.',
        SUPPLY_IIKO_DOCUMENT_PRINT_DATA_INCOMPLETE:
          'Недостаточно подтверждённых данных для печати.',
        SUPPLY_IIKO_DOCUMENT_PRODUCT_UNRESOLVED:
          'Не удалось однозначно определить название товара.',
        SUPPLY_IIKO_DOCUMENT_UNIT_UNRESOLVED:
          'Не удалось однозначно определить единицу товара.',
      } as Record<string, string>)[code ?? ''] ?? 'Не удалось сформировать PDF')
    }
  }

  async function sendToPrint() {
    if (busy || readOnly || printJobsState !== 'ready') return
    setBusy(true)
    setMessage('')
    try {
      if (normalPrintJob) {
        await reprintSupplyRequest(requestId, normalPrintJob.id)
      } else {
        await printSupplyRequest(requestId)
      }
      await reloadPrintJobs()
      setMessage(normalPrintJob
        ? 'Повторная печать поставлена в очередь'
        : 'Документ отправлен на печать')
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      setMessage(({
        SUPPLY_PRINT_NO_PRINTABLE_DOCUMENTS:
          'Нет полностью подтверждённых документов для печати.',
        SUPPLY_PRINT_PDF_CHANGED:
          'Документ изменился. Печать заблокирована.',
        SUPPLY_PRINT_PRINTER_NOT_ALLOWED:
          'Принтер не разрешён для этого контура.',
      } as Record<string, string>)[code ?? ''] ?? 'Не удалось отправить на печать')
    } finally {
      setBusy(false)
    }
  }

  async function reprint(jobId: string) {
    if (busy || readOnly) return
    setBusy(true)
    setMessage('')
    try {
      await reprintSupplyRequest(requestId, jobId)
      await reloadPrintJobs()
      setMessage('Повторная печать поставлена в очередь')
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      setMessage(code === 'SUPPLY_PRINT_PDF_CHANGED'
        ? 'Документ изменился. Повторная печать заблокирована.'
        : 'Не удалось повторить печать')
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
      setRequest(await cancelSupplyRequest(
        request.id,
        request.version,
        reason.trim(),
      ))
      setMessage('Заявка отменена')
    } catch {
      setMessage('Не удалось отменить заявку')
    } finally {
      setBusy(false)
    }
  }

  async function reloadSourcePreview() {
    if (!request) return
    setSourcePreview(await getSupplyProductSourcePreview(request.id))
    setSourceState('ready')
  }

  async function selectProductSource(productId: string, mappingId: string) {
    if (!request || !sourcePreview?.legal_contour || !mappingId || busy || hasDirty) return
    const product = sourcePreview.products.find((item) => item.product_id === productId)
    const replacement = product?.mapping_version != null
      && product.assigned_source?.mapping_id !== mappingId
    const comment = replacement
      ? window.prompt('Укажите обязательный комментарий для постоянной замены SOURCE')
      : null
    if (replacement && !comment?.trim()) return
    setBusy(true)
    setMessage('')
    try {
      await assignSupplyProductSource(
        productId,
        sourcePreview.legal_contour,
        mappingId,
        product?.mapping_version ?? null,
        comment?.trim() ?? null,
      )
      await reloadSourcePreview()
      setMessage(replacement ? 'SOURCE заменён' : 'SOURCE назначен')
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      if (code === 'VERSION_CONFLICT' || code === 'SUPPLY_PRODUCT_SOURCE_CONFLICT') {
        await reloadSourcePreview()
      }
      setMessage(({
        VERSION_CONFLICT:
          'Назначение SOURCE уже изменилось. Данные обновлены.',
        SUPPLY_PRODUCT_SOURCE_CONFLICT:
          'SOURCE уже назначен параллельно. Данные обновлены.',
        SUPPLY_PRODUCT_SOURCE_NOT_ALLOWED:
          'Этот SOURCE нельзя назначить товару.',
        SUPPLY_PRODUCT_SOURCE_PRODUCT_NOT_ELIGIBLE:
          'Сначала подтвердите IikoProductMapping товара.',
        SUPPLY_PRODUCT_SOURCE_REPLACEMENT_COMMENT_REQUIRED:
          'Для постоянной замены SOURCE обязателен комментарий.',
      } as Record<string, string>)[code ?? '']
        ?? 'Не удалось назначить SOURCE')
    } finally {
      setBusy(false)
    }
  }

  async function bootstrapProductSources() {
    if (busy || hasDirty) return
    setBusy(true)
    setMessage('')
    try {
      const result = await bootstrapSupplyProductSources()
      await reloadSourcePreview()
      setMessage(
        `Bootstrap: создано ${result.created}; уже назначено ${result.already_mapped}; конфликтов ${result.conflicts}; без SOURCE ${result.missing_source}; неоднозначно ${result.ambiguous_source}`,
      )
    } catch {
      setMessage('Не удалось выполнить bootstrap SOURCE')
    } finally {
      setBusy(false)
    }
  }

  function applyStockCalculation(calculation: SupplyStockCalculation) {
    setStockCalculation(calculation)
    setStockDrafts(Object.fromEntries(
      calculation.groups.flatMap((group) => group.lines)
        .filter((line) => line.transferable_quantity !== null)
        .map((line) => [line.id, line.transferable_quantity as string]),
    ))
    setStockCalculationState('ready')
  }

  async function calculateStock() {
    if (!request || busy || hasDirty) return
    setBusy(true)
    setMessage('')
    try {
      applyStockCalculation(await calculateSupplyStock(request.id))
      setMessage(stockCalculation
        ? 'Остатки пересчитаны. Результат предварительный.'
        : 'Остатки рассчитаны. Результат предварительный.')
    } catch {
      setMessage('Не удалось рассчитать остатки')
    } finally {
      setBusy(false)
    }
  }

  async function saveStockTransferable(lineId: string) {
    if (
      !request || !stockCalculation || busy
      || stockCalculation.status !== 'PRELIMINARY'
    ) return
    const line = stockCalculation.groups.flatMap((group) => group.lines)
      .find((item) => item.id === lineId)
    const quantity = stockDrafts[lineId]
    if (!line || quantity === line.transferable_quantity) return
    setBusy(true)
    setMessage('')
    try {
      applyStockCalculation(await updateSupplyStockTransferable(
        request.id,
        stockCalculation,
        line,
        quantity,
      ))
      setMessage('Количество к перемещению сохранено')
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      setStockDrafts((current) => ({
        ...current,
        [lineId]: line.transferable_quantity ?? '',
      }))
      if (code === 'VERSION_CONFLICT') {
        const current = await getSupplyStockCalculation(request.id)
        if (current) applyStockCalculation(current)
      }
      setMessage(({
        VERSION_CONFLICT:
          'Расчёт уже изменился. Данные обновлены, повторите действие.',
        SUPPLY_STOCK_TRANSFER_EXCEEDS_AVAILABLE:
          'Нельзя превысить количество строки или доступный остаток SOURCE.',
        SUPPLY_STOCK_TRANSFER_FRACTION_NOT_ALLOWED:
          'Для этой единицы разрешено только целое количество.',
        SUPPLY_STOCK_CALCULATION_CONFIRMED:
          'Расчёт уже подтверждён и недоступен для изменения.',
      } as Record<string, string>)[code ?? '']
        ?? 'Не удалось сохранить количество к перемещению')
    } finally {
      setBusy(false)
    }
  }

  async function confirmStock() {
    if (
      !request || !stockCalculation || busy || hasBlockedStock
      || stockCalculation.status !== 'PRELIMINARY'
    ) return
    setBusy(true)
    setMessage('')
    try {
      applyStockCalculation(await confirmSupplyStockCalculation(
        request.id,
        stockCalculation,
      ))
      setMessage('Расчёт подтверждён')
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      if (code === 'VERSION_CONFLICT') {
        const current = await getSupplyStockCalculation(request.id)
        if (current) applyStockCalculation(current)
      }
      setMessage(({
        VERSION_CONFLICT:
          'Расчёт уже изменился. Данные обновлены, проверьте его повторно.',
        SUPPLY_STOCK_CALCULATION_BLOCKED:
          'Подтверждение невозможно: устраните причины в заблокированных строках.',
        SUPPLY_STOCK_CALCULATION_CONFIRMED:
          'Этот расчёт уже подтверждён.',
      } as Record<string, string>)[code ?? '']
        ?? 'Не удалось подтвердить расчёт')
    } finally {
      setBusy(false)
    }
  }

  async function fulfillAsPlanned() {
    if (!request || busy || invalidFulfillment) return
    setBusy(true)
    setMessage('')
    try {
      setRequest(await fulfillSupplyAsPlanned(
        request.id,
        request.version,
        request.lines.map((line) => ({
          line_id: line.id,
          fulfilled_quantity: fulfillment[line.id] ?? '0',
        })),
      ))
      setFulfillment({})
      setMessage('Заявка завершена')
    } catch (error) {
      const code = error instanceof SupplyApiError ? error.code : null
      setMessage(({
        SUPPLY_DEBT_INCLUSION_CONFIRMATION_REQUIRED:
          'Для одной из строк сначала подтвердите включение старого долга',
        SUPPLY_DEBT_PRODUCT_REQUIRED:
          'Сначала сопоставьте строку с товаром EOS.',
        SUPPLY_SEND_QUANTITY_INVALID:
          'Для этой единицы разрешено только целое количество.',
        SUPPLY_REQUEST_VERSION_CONFLICT:
          'Заявка изменилась. Обновите карточку и повторите.',
      } as Record<string, string>)[code ?? ''] ?? 'Не удалось завершить заявку')
    } finally {
      setBusy(false)
    }
  }

  async function confirmDebt(line: SupplyLine) {
    if (!request || busy || !line.quantity) return
    const confirmed = window.confirm(
      `Подтвердить актуальное обязательство ${line.quantity} `
      + `${line.requested_unit?.short_name_ru ?? ''}?`,
    )
    if (!confirmed) return
    setBusy(true)
    try {
      setRequest(await confirmSupplyDebtInclusion(
        request.id,
        line.id,
        request.version,
        line.quantity,
      ))
      setMessage('Актуальное обязательство подтверждено')
    } catch {
      setMessage('Не удалось подтвердить включение долга')
    } finally {
      setBusy(false)
    }
  }

  async function increaseRequestToDebt(line: SupplyLine) {
    if (
      !request || busy || hasDirty || !line.requested_unit
      || !line.quantity || !line.active_debt_id
    ) return
    const entered = window.prompt(
      `Увеличьте количество заявки минимум до ${line.active_debt_quantity}`,
      line.active_debt_quantity,
    )
    if (entered === null || entered.trim() === '') return
    const enteredMillis = supplyQuantityMillis(entered)
    const debtMillis = supplyQuantityMillis(line.active_debt_quantity)
    if (enteredMillis === null || debtMillis === null || enteredMillis < debtMillis) {
      setMessage('Количество заявки должно быть не меньше активного долга')
      return
    }
    setBusy(true)
    setMessage('')
    try {
      const result = await saveSupplyLineWorkingValues(
        request.id,
        line.id,
        {
          request_version: request.version,
          working_name: line.working_name,
          requested_quantity: entered,
          send_quantity: line.send_quantity ?? line.quantity,
          requested_unit_id: line.requested_unit.id,
        },
      )
      setRequest({
        ...request,
        version: result.request_version,
        lines: request.lines.map((item) => (
          item.id === line.id ? result.line : item
        )),
      })
      setMessage('Количество заявки увеличено')
    } catch (error) {
      setMessage(workingSaveError(error))
    } finally {
      setBusy(false)
    }
  }

  async function mapLine(
    line: SupplyLine,
    workingDraft: SupplyLineWorkingDraft,
  ) {
    const draft = mapping[line.id]
    if (
      !request || busy || draft?.status === 'loading' || !draft
      || !isSupplyLineMatchReady(draft, workingDraft, units)
    ) return
    setMapping((current) => updateSupplyLineMappingDraft(
      current,
      line.id,
      draft,
      { status: 'loading', error: '' },
    ))
    try {
      const matchedLine = await matchSupplyLine(request.id, line.id, {
        expected_version: request.version,
        product_id: draft.productId,
        unit_id: workingDraft.unitId,
        quantity: workingDraft.quantity,
      })
      setMapping((current) => clearSupplyLineMappingDraft(current, line.id))
      const updated = await reload()
      if (matchedLine.context_mapping_suggestion) {
        setRequest({
          ...updated,
          lines: updated.lines.map((item) => item.id === line.id
            ? {
                ...item,
                context_mapping_suggestion:
                  matchedLine.context_mapping_suggestion,
              }
            : item),
        })
      }
      setMessage('Строка сопоставлена')
      const nextLineId = nextSupplyLineToMatch(updated.lines, line.id)
      if (nextLineId) {
        window.requestAnimationFrame(() => {
          const input = mappingInputRefs.current.get(nextLineId)
          input?.focus()
          input?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        })
      }
    } catch (error) {
      const conflict = error instanceof SupplyApiError
        && error.code === 'SUPPLY_ALIAS_CONFLICT'
      setMapping((current) => updateSupplyLineMappingDraft(
        current,
        line.id,
        draft,
        {
          status: 'error',
          error: conflict
            ? 'Это название уже связано с другим товаром EOS.'
            : 'Не удалось сопоставить строку.',
        },
      ))
    }
  }

  async function reparseLine(line: SupplyLine) {
    if (!request || busy || line.match_status !== 'NEEDS_REVIEW') return
    setBusy(true)
    setMessage('')
    try {
      const result = await reparseSupplyLine(
        request.id,
        line.id,
        request.version,
      )
      setWorking((current) => clearSupplyLineWorkingDraft(current, line.id))
      setRequest({
        ...request,
        version: result.request_version,
        lines: request.lines.map((item) => (
          item.id === line.id ? result.line : item
        )),
      })
      setMessage('Строка перераспознана')
    } catch (error) {
      const conflict = error instanceof SupplyApiError
        && error.code === 'SUPPLY_REQUEST_VERSION_CONFLICT'
      setMessage(conflict
        ? 'Заявка изменилась. Обновите карточку и повторите.'
        : 'Не удалось перераспознать строку.')
    } finally {
      setBusy(false)
    }
  }

  async function confirmContextMapping(line: SupplyLine) {
    const suggestion = line.context_mapping_suggestion
    if (!request || !suggestion || busy) return
    setBusy(true)
    setMessage('')
    try {
      await confirmSupplyContextMapping(
        request.id,
        line.id,
        suggestion.product_id,
        suggestion.mapping_version,
      )
      setRequest({
        ...request,
        lines: request.lines.map((item) => item.id === line.id
          ? { ...item, context_mapping_suggestion: null }
          : item),
      })
      setMessage('Контекстное правило сохранено для подразделения')
    } catch {
      setMessage('Не удалось сохранить контекстное правило')
    } finally {
      setBusy(false)
    }
  }

  if (state === 'loading') {
    return <p className="page-state">Загружаем заявку…</p>
  }
  if (state === 'error' || !request) {
    return (
      <p className="request-message request-message-error">
        Заявка не найдена или недоступна
      </p>
    )
  }

  if (readOnly) {
    return <SupplyRequestReadOnlyCard request={request} />
  }

  return (
    <section className="request-page request-detail-page supply-admin-page">
      <div className="request-panel">
        <div className="request-heading supply-simple-heading">
          <div>
            <p className="eyebrow">СНАБЖЕНИЕ</p>
            <h1>{request.public_number}</h1>
            <p>
              {request.department.name} · {request.direction.name}
              {' · '}{statusLabel(request.status)}
            </p>
          </div>
          <Link className="request-back-link" to="/supply/requests">
            ← К реестру
          </Link>
        </div>
        <div className="supply-request-meta">
          <span>{request.public_author_name ?? 'Не указано'}</span>
          <span>{formatDate(request.submitted_at ?? request.created_at)}</span>
          <details>
            <summary>Действия с заявкой</summary>
            <button type="button" disabled={busy} onClick={() => void reload()}>
              Обновить
            </button>
            {editable && (
              <button
                type="button"
                disabled={busy || hasDirty}
                onClick={() => void cancel()}
              >
                Отменить заявку
              </button>
            )}
          </details>
        </div>
        <div className="supply-match-progress" aria-live="polite">
          <strong>
            Сопоставлено: {matchProgress.matched} из {matchProgress.total}
          </strong>
          <span>Требуют проверки: {matchProgress.needsReview}</span>
        </div>

        <section className="supply-iiko-stock-check" aria-label="Распределение по SOURCE">
          <div className="supply-iiko-stock-heading">
            <div>
              <strong>
                SOURCE назначен: {sourcePreview?.assigned_products ?? 0} из{' '}
                {sourcePreview?.total_products ?? 0}
              </strong>
              <small>
                Постоянный маршрут товара для legal contour заявки
              </small>
            </div>
            <button
              type="button"
              disabled={busy || hasDirty || sourceState !== 'ready'}
              onClick={() => void bootstrapProductSources()}
            >
              Bootstrap SOURCE
            </button>
          </div>
          {sourceState === 'loading' && <p>Загружаем распределение…</p>}
          {sourceState === 'error' && (
            <p className="request-message-error">
              Не удалось загрузить распределение SOURCE.
            </p>
          )}
          {sourceState === 'ready' && !sourcePreview?.legal_contour && (
            <p>Распределение невозможно: у подразделения не указан legal contour.</p>
          )}
          {sourceState === 'ready' && sourcePreview?.products.length ? (
            <div className="supply-iiko-stock-lines">
              {sourcePreview.products.map((product) => (
                <div className="supply-iiko-stock-line" key={product.product_id}>
                  <strong>{product.product_name}</strong>
                  <span>{product.role ?? 'Роль не определена'}</span>
                  <EosSelect
                    aria-label={`SOURCE для ${product.product_name}`}
                    value={product.assigned_source?.mapping_id ?? ''}
                    disabled={busy || hasDirty || !product.iiko_mapping_confirmed
                      || !product.role || product.available_sources.length === 0}
                    onChange={(event) => void selectProductSource(
                      product.product_id,
                      event.target.value,
                    )}
                  >
                    <option value="">Выберите SOURCE</option>
                    {product.available_sources.map((source) => (
                      <option value={source.mapping_id} key={source.mapping_id}>
                        {source.name}
                      </option>
                    ))}
                  </EosSelect>
                  {product.blocking_reason ? (
                    <span className="supply-iiko-stock-unavailable">
                      {product.blocking_reason}
                    </span>
                  ) : (
                    <strong className="supply-iiko-stock-enough">Назначен</strong>
                  )}
                </div>
              ))}
            </div>
          ) : null}
          {sourceState === 'ready' && sourcePreview?.blocking_reasons.map((reason) => (
            <p className="supply-iiko-stock-unavailable" key={reason}>{reason}</p>
          ))}
          {sourceState === 'ready' && sourcePreview?.groups.length ? (
            <div className="supply-source-groups">
              <strong>Read-only preview групп по складам</strong>
              {sourcePreview.groups.map((group) => (
                <div className="supply-source-group" key={group.source.mapping_id}>
                  <b>{group.source.name}</b>
                  <ul>
                    {group.lines.map((line) => (
                      <li key={line.line_id}>
                        {line.product_name} — {line.quantity ?? '—'}{' '}
                        {line.unit?.short_name_ru ?? ''}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
              <small>Каждая будущая накладная/ВП — только для одного SOURCE.</small>
            </div>
          ) : null}
        </section>

        {(iikoDocuments.length > 0 || printJobs.length > 0) && (
          <section className="supply-stock-calculation" aria-label="Документы iiko">
            <div className="supply-iiko-stock-heading">
              <div>
                <strong>Документы iiko</strong>
                <small>Расходные накладные по SOURCE</small>
              </div>
              {printableIikoDocuments.length > 0 && (
                <button
                  type="button"
                  onClick={() => void downloadIikoPdf()}
                >
                  Печать всех
                </button>
              )}
              {!readOnly && printableIikoDocuments.length > 0 && (
                <button
                  type="button"
                  disabled={busy || printJobsState !== 'ready'}
                  onClick={() => void sendToPrint()}
                >
                  {normalPrintJob
                    ? 'Отправить повторно'
                    : 'Отправить на печать'}
                </button>
              )}
            </div>
            {!readOnly && printableIikoDocuments.length > 0
              && printJobsState === 'error' && (
              <small className="request-message-error">
                Не удалось загрузить историю печати. Отправка временно недоступна.
              </small>
            )}
            <div className="supply-source-groups">
              {iikoDocuments.map((document) => (
                <div
                  className="supply-source-group"
                  key={`${document.source_store_id}:${document.document_type}`}
                >
                  <b>{document.flow}</b>
                  <small>SOURCE: {document.source_store_id}</small>
                  <span>Статус: {document.status}</span>
                  {document.document_number && (
                    <span>Номер: {document.document_number}</span>
                  )}
                  {document.status === 'UNKNOWN' && (
                    <strong>{document.operator_message}</strong>
                  )}
                  {document.status === 'FAILED' && document.error_code && (
                    <small>Код ошибки: {document.error_code}</small>
                  )}
                  {document.printable && (
                    <button
                      type="button"
                      onClick={() => void downloadIikoPdf(
                        document.document_write_id,
                      )}
                    >
                      PDF
                    </button>
                  )}
                </div>
              ))}
            </div>
            {printJobs.length > 0 && (
              <div className="supply-source-groups" aria-label="История печати">
                <strong>История печати</strong>
                {printJobs.map((job) => (
                  <div className="supply-source-group" key={job.id}>
                    <strong>{supplyPrintPurposeLabel(job.purpose)}</strong>
                    <span>Статус: {supplyPrintStatusLabel(job.status)}</span>
                    <small>Дата: {formatDate(job.created_at)}</small>
                    {job.status === 'PRINT_FAILED' && !readOnly && (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void reprint(job.id)}
                      >
                        Повторить печать
                      </button>
                    )}
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        <section className="supply-stock-calculation" aria-label="Сверка остатков">
          <div className="supply-iiko-stock-heading">
            <div>
              <strong>Сверка остатков</strong>
              <small>
                {stockCalculation?.is_preliminary
                  ? 'Предварительный расчёт'
                  : stockCalculation ? 'Расчёт подтверждён' : 'Расчёт ещё не выполнен'}
              </small>
            </div>
            <div className="supply-stock-actions">
              <button
                type="button"
                disabled={busy || hasDirty || hasStockDraft}
                onClick={() => void calculateStock()}
              >
                Рассчитать по остаткам
              </button>
              <button
                type="button"
                disabled={busy || hasDirty || hasStockDraft
                  || hasBlockedStock || !stockCalculation
                  || stockCalculation.status !== 'PRELIMINARY'}
                onClick={() => void confirmStock()}
              >
                Подтвердить расчёт
              </button>
            </div>
          </div>
          {stockCalculationState === 'loading' && <p>Загружаем расчёт…</p>}
          {stockCalculationState === 'error' && (
            <p className="request-message-error">Не удалось загрузить расчёт остатков.</p>
          )}
          {stockCalculation?.status === 'CONFIRMED' && (
            <p className="supply-stock-dates">
              Дата расчёта: {formatDate(stockCalculation.calculated_at)} · Дата снимка iiko:{' '}
              {formatDate(stockCalculation.snapshot_at)}
            </p>
          )}
          {stockCalculation?.groups.map((group) => (
            <div className="supply-stock-group" key={group.source_mapping_id ?? 'blocked'}>
              <div className="supply-stock-group-title">
                <strong>{group.source_name ?? 'Заблокированные строки'}</strong>
                {stockCalculation.status === 'CONFIRMED' && group.snapshot_at && (
                  <small>Снимок iiko: {formatDate(group.snapshot_at)}</small>
                )}
              </div>
              <div className="supply-stock-grid supply-stock-grid-head" role="row">
                <span>Товар</span>
                <span>Запрошено</span>
                <span>Остаток</span>
                <span>К перемещению</span>
                <span>Дефицит</span>
              </div>
              {group.lines.map((line) => (
                <div className="supply-stock-grid" key={line.id} role="row">
                  <strong>{line.product_name}</strong>
                  <span>
                    {line.requested_quantity ?? '—'} {line.requested_unit?.short_name_ru ?? ''}
                  </span>
                  <span>{line.available_quantity ?? '—'}</span>
                  {line.unavailable_reason ? (
                    <span className="supply-iiko-stock-unavailable">
                      {line.unavailable_reason}
                    </span>
                  ) : (
                    <input
                      aria-label={`К перемещению для ${line.product_name}`}
                      type="number"
                      min="0"
                      max={line.requested_quantity ?? undefined}
                      step={line.requested_unit?.allows_fraction ? '0.001' : '1'}
                      value={stockDrafts[line.id] ?? ''}
                      disabled={busy || stockCalculation.status === 'CONFIRMED'}
                      onChange={(event) => setStockDrafts((current) => ({
                        ...current,
                        [line.id]: event.target.value,
                      }))}
                      onBlur={() => void saveStockTransferable(line.id)}
                    />
                  )}
                  {!line.unavailable_reason && <span>{line.deficit_quantity ?? '—'}</span>}
                </div>
              ))}
            </div>
          ))}
        </section>

        <div className="supply-simple-table" role="table">
          <div className="supply-simple-table-head" role="row">
            <span role="columnheader">Название</span>
            <span role="columnheader">
              {['PLANNED', 'PARTIALLY_FULFILLED', 'FULFILLED'].includes(
                request.status,
              ) ? 'Отправлено' : 'Отправить'}
            </span>
            <span role="columnheader">Фасовка / единица</span>
            <span aria-hidden="true" />
          </div>
          {request.lines.map((line) => {
            const lineEditable = editable
              && line.debt_inclusion_status !== 'CONFIRMED_PARTIAL'
            const canMapLine = lineEditable || (
              line.active_debt_requires_matching
              && !!line.active_debt_id
              && ['PLANNED', 'PARTIALLY_FULFILLED', 'FULFILLED'].includes(
                request.status,
              )
            )
            const baseline = supplyLineWorkingBaseline(line)
            const draft = getSupplyLineWorkingDraft(
              working,
              line.id,
              baseline,
            )
            const mappingDraft = getSupplyLineMappingDraft(
              mapping,
              line.id,
              suggestSupplyWorkingName(line.parsed_name, line.raw_text),
            )
            const updateMapping = (
              changes: Parameters<typeof updateSupplyLineMappingDraft>[3],
            ) => setMapping((current) => updateSupplyLineMappingDraft(
              current,
              line.id,
              mappingDraft,
              changes,
            ))
            const lineDirty = dirtySet.has(line.id)
            const requested = supplyQuantityMillis(line.quantity ?? '')
            const sending = supplyQuantityMillis(draft.quantity)
            const expectedDebt = supplyExpectedDebtMillis(
              line.quantity ?? '',
              draft.quantity,
            )
            const sendExcess = supplySendExcessMillis(
              line.quantity ?? '',
              draft.quantity,
            )
            const sendDiffers = requested !== null
              && sending !== null
              && requested !== sending
            const fulfillmentMillis = supplyQuantityMillis(
              fulfillment[line.id] ?? '0',
            )
            const completedExcess = supplySendExcessMillis(
              line.quantity ?? '',
              line.fulfilled_total,
            )
            return (
              <div
                className={[
                  'supply-simple-line',
                  lineDirty ? 'is-dirty' : '',
                  draft.status === 'error' ? 'has-error' : '',
                ].filter(Boolean).join(' ')}
                role="row"
                key={line.id}
              >
                <div className="supply-simple-name" role="cell">
                  {lineEditable ? (
                    <input
                      aria-label={`Название, строка ${line.position}`}
                      value={draft.workingName}
                      disabled={busy}
                      onChange={(event) => changeWorking(
                        line,
                        draft,
                        { workingName: event.target.value },
                      )}
                    />
                  ) : <span>{line.working_name}</span>}
                  {!line.product_id && (
                    <small className="supply-unmatched-badge">
                      Не сопоставлено
                    </small>
                  )}
                </div>
                <div role="cell">
                  {lineEditable ? (
                    <input
                      className="supply-simple-quantity"
                      aria-label={`Отправить, строка ${line.position}`}
                      type="number"
                      min="0"
                      step="0.001"
                      inputMode="decimal"
                      value={draft.quantity}
                      disabled={busy}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter') event.currentTarget.blur()
                      }}
                      onChange={(event) => changeWorking(
                        line,
                        draft,
                        { quantity: event.target.value },
                      )}
                    />
                  ) : request.status === 'PLANNED' ? (
                    <input
                      className="supply-simple-quantity"
                      aria-label={`Отправлено, строка ${line.position}`}
                      type="number"
                      min="0"
                      step={line.requested_unit?.allows_fraction ? '0.001' : '1'}
                      inputMode={line.requested_unit?.allows_fraction
                        ? 'decimal'
                        : 'numeric'}
                      value={fulfillment[line.id] ?? '0'}
                      disabled={busy}
                      onChange={(event) => setFulfillment((current) => ({
                        ...current,
                        [line.id]: event.target.value,
                      }))}
                    />
                  ) : ['PARTIALLY_FULFILLED', 'FULFILLED'].includes(
                    request.status,
                  ) ? (
                    <>
                      <span>{line.fulfilled_total}</span>
                      <small className="supply-send-summary">
                        Остаток: {line.unresolved_quantity}
                      </small>
                      {completedExcess !== null && completedExcess > 0 && (
                        <small className="supply-send-summary">
                          Сверх заявки:{' '}
                          {formatSupplyQuantityMillis(completedExcess)}
                        </small>
                      )}
                    </>
                  ) : (
                    <span>{line.send_quantity ?? line.quantity ?? '—'}</span>
                  )}
                  {request.status === 'PLANNED'
                    && requested !== null
                    && fulfillmentMillis !== null && (
                    <small className="supply-send-summary">
                      Утверждено: {line.quantity}
                      {' · '}остаток:{' '}
                      {formatSupplyQuantityMillis(Math.max(
                        requested - fulfillmentMillis,
                        0,
                      ))}
                    </small>
                  )}
                  {lineEditable && sendDiffers
                    && expectedDebt !== null && expectedDebt > 0 && (
                    <small className="supply-send-summary">
                      Запрошено: {line.quantity}
                      {' · '}долг после отправки:{' '}
                      {formatSupplyQuantityMillis(expectedDebt)}
                    </small>
                  )}
                  {lineEditable && sendDiffers
                    && sendExcess !== null && sendExcess > 0 && (
                    <small className="supply-send-summary">
                      Отправлено больше запроса на{' '}
                      {formatSupplyQuantityMillis(sendExcess)} единиц
                    </small>
                  )}
                </div>
                <div role="cell">
                  {lineEditable ? (
                    <EosSelect
                      aria-label={`Фасовка, строка ${line.position}`}
                      value={draft.unitId}
                      disabled={busy}
                      onChange={(event) => changeWorking(
                        line,
                        draft,
                        { unitId: event.target.value },
                      )}
                    >
                      <option value="">Выберите</option>
                      {units.map((unit) => (
                        <option value={unit.id} key={unit.id}>
                          {unit.short_name_ru}
                        </option>
                      ))}
                    </EosSelect>
                  ) : (
                    <span>
                      {line.requested_unit?.short_name_ru
                        ?? line.parsed_unit?.short_name_ru
                        ?? '—'}
                    </span>
                  )}
                </div>
                <span role="cell" aria-hidden="true" />
                {(requiresSupplyLineMatch(line)
                  || line.active_debt_requires_matching) && (
                  <SupplyLineMappingEditor
                    line={line}
                    draft={mappingDraft}
                    workingDraft={draft}
                    units={units}
                    disabled={busy || !canMapLine}
                    onChange={updateMapping}
                    onMatch={() => void mapLine(line, draft)}
                    onReparse={() => void reparseLine(line)}
                    inputRef={(element) => {
                      if (element) {
                        mappingInputRefs.current.set(line.id, element)
                      } else {
                        mappingInputRefs.current.delete(line.id)
                      }
                    }}
                  />
                )}
                {draft.error && (
                  <small className="supply-line-error">{draft.error}</small>
                )}
                {line.context_mapping_suggestion && (
                  <div className="request-message request-message-warning">
                    Вы уже {line.context_mapping_suggestion.correction_count}
                    {' '}раза сопоставили «{line.context_mapping_suggestion.phrase}»
                    {' '}с товаром «{line.context_mapping_suggestion.product_name}»
                    для этого подразделения. Сохранить правило для следующих
                    заявок?
                    <button
                      type="button"
                      disabled={busy}
                      onClick={() => void confirmContextMapping(line)}
                    >
                      Сохранить контекстное правило
                    </button>
                  </div>
                )}
                {line.active_debt_id && (
                  <div className="request-message request-message-warning">
                    Активный долг: {line.active_debt_quantity}{' '}
                    {line.requested_unit?.short_name_ru ?? ''}.
                    {line.requires_debt_confirmation && (
                      <>
                        {' '}Увеличьте заявку либо подтвердите меньшее
                        актуальное количество.
                        <button
                          type="button"
                          disabled={busy || hasDirty}
                          onClick={() => void increaseRequestToDebt(line)}
                        >
                          Увеличить заявку
                        </button>
                        <button
                          type="button"
                          disabled={busy || hasDirty}
                          onClick={() => void confirmDebt(line)}
                        >
                          Подтвердить меньшее количество
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {['PLANNED', 'PARTIALLY_FULFILLED', 'FULFILLED'].includes(
          request.status,
        ) && request.lines.map((line) => (
          <details className="supply-fulfillment" key={`fact-${line.id}`}>
            <summary>
              {line.working_name}: отправлено {line.fulfilled_total} из{' '}
              {line.quantity ?? '—'}
            </summary>
            <dl className="supply-line-totals">
              <div><dt>Утверждено</dt><dd>{line.quantity ?? '—'}</dd></div>
              <div><dt>Отправлено</dt><dd>{line.fulfilled_total}</dd></div>
              <div><dt>Осталось</dt><dd>{line.unresolved_quantity}</dd></div>
              <SupplyExcessFact line={line} />
              {line.active_debt_id && (
                <div>
                  <dt>Активный долг</dt>
                  <dd>{line.active_debt_quantity}</dd>
                </div>
              )}
            </dl>
            {line.requires_debt_confirmation
              && request.status === 'PLANNED' && (
              <div className="request-message request-message-warning">
                Подтвердите актуальное обязательство.
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
            {line.send_quantity === null && request.status === 'PLANNED' && (
              <FulfillmentEditor
                request={request}
                line={line}
                onSaved={setRequest}
              />
            )}
          </details>
        ))}
      </div>

      <div className="supply-sticky-actions">
        {message && <span role="status">{message}</span>}
        {editable && hasDirty && (
          <button
            className="supply-primary-action"
            type="button"
            disabled={busy || invalidDirty}
            onClick={() => void saveAllWorkingValues()}
          >
            {busy ? 'Сохраняем…' : 'Сохранить изменения'}
          </button>
        )}
        {editable && !hasDirty && (
          <button
            className="supply-primary-action"
            type="button"
            disabled={busy || !readyToSend}
            onClick={() => void sendToWork()}
          >
            {busy ? 'Отправляем…' : 'Отправить в работу'}
          </button>
        )}
        {request.status === 'PLANNED' && (
          iikoDocuments.length === 0
          || iikoDocuments.some((document) => document.status !== 'CREATED')
        ) && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void sendToWork()}
          >
            {busy ? 'Проверяем…' : 'Повторить «Отдать в работу»'}
          </button>
        )}
        {request.status === 'PLANNED' && (
          <button
            className="supply-primary-action"
            type="button"
            disabled={busy || invalidFulfillment}
            onClick={() => void fulfillAsPlanned()}
          >
            {busy ? 'Завершаем…' : 'Завершить заявку'}
          </button>
        )}
        {request.status === 'PLANNED' && invalidFulfillment && (
          <small className="request-message-error">
            Проверьте фактически отправленное количество.
          </small>
        )}
      </div>
    </section>
  )
}

export default SupplyRequestDetailPage
