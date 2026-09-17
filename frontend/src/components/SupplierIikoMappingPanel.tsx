import { useEffect, useState } from 'react'
import {
  confirmSupplySupplierIikoMapping,
  getIikoSupplierReferences,
  getSupplySupplierIikoMapping,
  type IikoSupplierReference,
  type SupplySupplier,
  type SupplySupplierIikoMappingState,
} from '../services/supplyAdmin'
import { supplierErrorMessage } from '../pages/supplySupplierLogic'

type Props = {
  supplier: SupplySupplier
}

export default function SupplierIikoMappingPanel({ supplier }: Props) {
  const [state, setState] = useState<SupplySupplierIikoMappingState | null>(null)
  const [searchOpen, setSearchOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [items, setItems] = useState<IikoSupplierReference[]>([])
  const [selected, setSelected] = useState<IikoSupplierReference | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    getSupplySupplierIikoMapping(supplier.id, controller.signal)
      .then(setState)
      .catch((requestError) => {
        if (!controller.signal.aborted) {
          setError(supplierErrorMessage(requestError, 'Не удалось загрузить связь с iiko'))
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [supplier.id])

  useEffect(() => {
    if (!searchOpen) return
    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      getIikoSupplierReferences(
        supplier.id, search, includeDeleted, controller.signal,
      ).then((page) => setItems(page.items)).catch((requestError) => {
        if (!controller.signal.aborted) {
          setError(supplierErrorMessage(requestError, 'Не удалось найти поставщиков iiko'))
        }
      })
    }, 200)
    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [includeDeleted, search, searchOpen, supplier.id])

  async function confirmMapping() {
    if (!selected) return
    if (state?.mapping && !window.confirm(
      `Изменить сопоставление с «${state.mapping.iiko_supplier_name}» на «${selected.name}»?`,
    )) return
    setBusy(true)
    setError('')
    try {
      const updated = await confirmSupplySupplierIikoMapping(
        supplier.id, selected.external_id,
      )
      setState(updated)
      setSearchOpen(false)
      setSelected(null)
      setSearch('')
    } catch (requestError) {
      setError(supplierErrorMessage(requestError, 'Не удалось подтвердить сопоставление'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="supplier-iiko-panel" aria-labelledby="supplier-iiko-title">
      <div className="supplier-form-heading">
        <div>
          <p className="eyebrow">IIKO</p>
          <h2 id="supplier-iiko-title">Связь с iiko</h2>
        </div>
        {state?.mapping && (
          <span className={state.iiko_receipt_ready_supplier_mapping ? 'badge badge-active' : 'badge badge-blocked'}>
            {state.iiko_receipt_ready_supplier_mapping ? 'Подтверждено' : 'Требует внимания'}
          </span>
        )}
      </div>

      {loading && <p>Загружаем сопоставление…</p>}
      {!loading && !state?.mapping && <p>Поставщик ещё не сопоставлен с iiko.</p>}
      {state?.mapping && (
        <div className="supplier-iiko-summary">
          <div><small>EOS</small><strong>{supplier.display_name}</strong></div>
          <div>
            <small>iiko</small>
            <strong>{state.mapping.iiko_supplier_name}</strong>
            {state.mapping.iiko_supplier_code && <span>Код: {state.mapping.iiko_supplier_code}</span>}
            {state.mapping.iiko_supplier_inn && <span>ИНН: {state.mapping.iiko_supplier_inn}</span>}
          </div>
        </div>
      )}
      {state?.warning && <p className="request-message request-message-error" role="alert">{state.warning}</p>}
      {error && <p className="request-message request-message-error" role="alert">{error}</p>}

      {!searchOpen ? (
        <button
          className="secondary-action"
          type="button"
          disabled={loading || !supplier.is_active}
          onClick={() => {
            setSearchOpen(true)
            setError('')
          }}
        >
          {state?.mapping ? 'Изменить сопоставление' : 'Сопоставить'}
        </button>
      ) : (
        <div className="supplier-iiko-search">
          <label>
            <span>Поставщик iiko</span>
            <input
              value={search}
              placeholder="Название или код"
              maxLength={240}
              autoFocus
              onChange={(event) => {
                setSearch(event.target.value)
                setSelected(null)
              }}
            />
          </label>
          <label className="supplier-iiko-checkbox">
            <input
              type="checkbox"
              checked={includeDeleted}
              onChange={(event) => setIncludeDeleted(event.target.checked)}
            />
            Показывать удалённых
          </label>
          <div className="supplier-iiko-results" role="listbox" aria-label="Поставщики iiko">
            {items.map((item) => (
              <button
                key={item.external_id}
                type="button"
                role="option"
                aria-selected={selected?.external_id === item.external_id}
                className={selected?.external_id === item.external_id ? 'is-selected' : ''}
                disabled={item.is_deleted || !item.is_active}
                onClick={() => setSelected(item)}
              >
                <strong>{item.name}</strong>
                <span>
                  {item.code ? `Код: ${item.code}` : 'Без кода'}
                  {item.inn ? ` · ИНН: ${item.inn}` : ''}
                  {item.exact_inn_match ? ' · Точное совпадение ИНН' : ''}
                  {item.is_deleted ? ' · Удалён в iiko' : ''}
                </span>
              </button>
            ))}
            {items.length === 0 && <p>Совпадений не найдено.</p>}
          </div>
          <div className="supplier-form-actions">
            <button className="primary-action" type="button" disabled={!selected || busy} onClick={() => void confirmMapping()}>
              {busy ? 'Подтверждаем…' : 'Подтвердить'}
            </button>
            <button className="secondary-action" type="button" disabled={busy} onClick={() => setSearchOpen(false)}>
              Отмена
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
