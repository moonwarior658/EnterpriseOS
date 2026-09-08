import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  archiveSupplyProductSupplier,
  createSupplyProductSupplier,
  getSupplyProductSupplierPriceHistory,
  getSupplyProductSuppliers,
  getSupplySuppliers,
  getSupplyUnits,
  makePrimarySupplyProductSupplier,
  restoreSupplyProductSupplier,
  SupplyApiError,
  updateSupplyProductSupplier,
  type SupplyProductSupplier,
  type SupplyProductSupplierPriceHistory,
  type SupplySupplier,
  type SupplyUnit,
} from '../services/supplyAdmin'
import './SupplyProductSuppliersPanel.css'

type Props = { productId: string; productName: string; onClose: () => void }

type Draft = {
  supplierId: string
  supplierProductName: string
  supplierSku: string
  priority: string
  packageQuantity: string
  packageUnitId: string
  pricePerPackage: string
  isAvailable: boolean
  unavailableUntil: string
}

const EMPTY_DRAFT: Draft = {
  supplierId: '', supplierProductName: '', supplierSku: '', priority: '100',
  packageQuantity: '', packageUnitId: '', pricePerPackage: '',
  isAvailable: true, unavailableUntil: '',
}

function productSupplierErrorMessage(error: unknown): string {
  if (!(error instanceof SupplyApiError)) return 'Не удалось выполнить действие'
  if (error.status === 409) return 'Условия конфликтуют с активной связью или основным поставщиком'
  if (error.status === 404) return 'Товар, поставщик или связь не найдены. Обновите данные.'
  if (error.status === 403) return 'Недостаточно прав для управления поставщиками товара'
  if (error.status === 422) return 'Проверьте упаковку, цену и доступность'
  return 'Не удалось выполнить действие'
}

function draftFromRelation(relation: SupplyProductSupplier): Draft {
  return {
    supplierId: relation.supplier_id,
    supplierProductName: relation.supplier_product_name ?? '',
    supplierSku: relation.supplier_sku ?? '',
    priority: String(relation.priority),
    packageQuantity: relation.package_quantity,
    packageUnitId: relation.package_unit_id,
    pricePerPackage: relation.price_per_package ?? '',
    isAvailable: relation.is_available,
    unavailableUntil: relation.unavailable_until ?? '',
  }
}

function money(value: string | null): string {
  if (value === null) return 'Не указана'
  return `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(Number(value))} ₽`
}

function historyDate(value: string): string {
  return new Date(value).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

export function SupplyProductSuppliersPanel({ productId, productName, onClose }: Props) {
  const [relations, setRelations] = useState<SupplyProductSupplier[]>([])
  const [suppliers, setSuppliers] = useState<SupplySupplier[]>([])
  const [units, setUnits] = useState<SupplyUnit[]>([])
  const [showArchive, setShowArchive] = useState(false)
  const [editing, setEditing] = useState<SupplyProductSupplier | 'new' | null>(null)
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [historyRelationId, setHistoryRelationId] = useState<string | null>(null)
  const [history, setHistory] = useState<SupplyProductSupplierPriceHistory[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [items, supplierPage, unitItems] = await Promise.all([
        getSupplyProductSuppliers(productId, !showArchive),
        getSupplySuppliers(true, '', 0, 100),
        getSupplyUnits(),
      ])
      setRelations(items)
      setSuppliers(supplierPage.items)
      setUnits(unitItems.filter((unit) => unit.is_active))
    } catch (loadError) {
      setError(productSupplierErrorMessage(loadError))
    } finally {
      setLoading(false)
    }
  }, [productId, showArchive])

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timeout)
  }, [load])

  function beginCreate() {
    setDraft({ ...EMPTY_DRAFT, packageUnitId: units[0]?.id ?? '' })
    setEditing('new')
    setError('')
  }

  function beginEdit(relation: SupplyProductSupplier) {
    setDraft(draftFromRelation(relation))
    setEditing(relation)
    setError('')
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    const priority = Number(draft.priority)
    const quantity = Number(draft.packageQuantity)
    const price = draft.pricePerPackage === '' ? null : Number(draft.pricePerPackage)
    if (!draft.supplierId || !draft.packageUnitId || !Number.isInteger(priority) || priority < 0 || !Number.isFinite(quantity) || quantity <= 0 || (price !== null && (!Number.isFinite(price) || price <= 0))) {
      setError('Заполните поставщика, упаковку, положительное количество и корректную цену')
      return
    }
    setBusy(true)
    setError('')
    const payload = {
      supplier_product_name: draft.supplierProductName.trim() || null,
      supplier_sku: draft.supplierSku.trim() || null,
      priority,
      package_quantity: draft.packageQuantity,
      package_unit_id: draft.packageUnitId,
      price_per_package: draft.pricePerPackage || null,
      currency: 'RUB' as const,
      is_available: draft.isAvailable,
      unavailable_until: draft.isAvailable ? null : draft.unavailableUntil || null,
    }
    try {
      if (editing === 'new') {
        await createSupplyProductSupplier(productId, {
          ...payload, supplier_id: draft.supplierId, role: 'BACKUP',
        })
      } else if (editing) {
        await updateSupplyProductSupplier(productId, editing.id, payload)
      }
      setEditing(null)
      await load()
    } catch (submitError) {
      setError(productSupplierErrorMessage(submitError))
    } finally {
      setBusy(false)
    }
  }

  async function act(relation: SupplyProductSupplier, action: 'archive' | 'restore' | 'primary') {
    if (action === 'archive' && !window.confirm(`Архивировать связь с «${relation.supplier.display_name}»?`)) return
    setBusy(true)
    setError('')
    try {
      if (action === 'archive') await archiveSupplyProductSupplier(productId, relation.id)
      else if (action === 'restore') await restoreSupplyProductSupplier(productId, relation.id)
      else await makePrimarySupplyProductSupplier(productId, relation.id)
      await load()
    } catch (actionError) {
      setError(productSupplierErrorMessage(actionError))
    } finally {
      setBusy(false)
    }
  }

  async function toggleHistory(relation: SupplyProductSupplier) {
    if (historyRelationId === relation.id) {
      setHistoryRelationId(null)
      setHistory([])
      setHistoryError('')
      return
    }
    setHistoryRelationId(relation.id)
    setHistory([])
    setHistoryError('')
    setHistoryLoading(true)
    try {
      setHistory(await getSupplyProductSupplierPriceHistory(productId, relation.id))
    } catch (loadError) {
      setHistoryError(productSupplierErrorMessage(loadError))
    } finally {
      setHistoryLoading(false)
    }
  }

  const linkedSupplierIds = new Set(relations.filter((item) => item.is_active).map((item) => item.supplier_id))

  return (
    <div className="product-suppliers-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section className="product-suppliers-panel" role="dialog" aria-modal="true" aria-labelledby="product-suppliers-title">
        <header>
          <div><p className="eyebrow">Товар EOS</p><h2 id="product-suppliers-title">{productName}</h2></div>
          <button type="button" className="secondary-action" onClick={onClose}>Закрыть</button>
        </header>
        <div className="product-suppliers-toolbar">
          <h3>Поставщики</h3>
          <div>
            <button type="button" className="secondary-action" disabled={busy} onClick={() => { setShowArchive((value) => !value); setEditing(null) }}>{showArchive ? 'Активные' : 'Архив'}</button>
            {!showArchive && <button type="button" className="primary-action" disabled={busy} onClick={beginCreate}>Добавить поставщика</button>}
          </div>
        </div>
        {error && <p className="request-message request-message-error" role="alert">{error}</p>}
        {editing && (
          <form className="product-supplier-form" onSubmit={(event) => void submit(event)}>
            <label><span>Поставщик</span><select value={draft.supplierId} disabled={editing !== 'new' || busy} onChange={(event) => setDraft({ ...draft, supplierId: event.target.value })}><option value="">Выберите поставщика</option>{suppliers.filter((supplier) => editing !== 'new' || !linkedSupplierIds.has(supplier.id)).map((supplier) => <option key={supplier.id} value={supplier.id}>{supplier.display_name}{supplier.inn ? ` · ИНН ${supplier.inn}` : ''}</option>)}</select></label>
            <label><span>Название у поставщика</span><input value={draft.supplierProductName} maxLength={240} onChange={(event) => setDraft({ ...draft, supplierProductName: event.target.value })} /></label>
            <label><span>Артикул поставщика</span><input value={draft.supplierSku} maxLength={120} onChange={(event) => setDraft({ ...draft, supplierSku: event.target.value })} /></label>
            <label><span>Приоритет</span><input type="number" min="0" step="1" value={draft.priority} onChange={(event) => setDraft({ ...draft, priority: event.target.value })} /></label>
            <label><span>Количество базовых единиц в упаковке</span><input type="number" min="0.001" step="0.001" value={draft.packageQuantity} onChange={(event) => setDraft({ ...draft, packageQuantity: event.target.value })} /></label>
            <label><span>Тип упаковки</span><select value={draft.packageUnitId} onChange={(event) => setDraft({ ...draft, packageUnitId: event.target.value })}><option value="">Выберите единицу</option>{units.map((unit) => <option key={unit.id} value={unit.id}>{unit.name_ru}</option>)}</select></label>
            <label><span>Цена упаковки, ₽</span><input type="number" min="0.01" step="0.01" value={draft.pricePerPackage} onChange={(event) => setDraft({ ...draft, pricePerPackage: event.target.value })} /></label>
            <label className="product-supplier-available"><input type="checkbox" checked={draft.isAvailable} onChange={(event) => setDraft({ ...draft, isAvailable: event.target.checked, unavailableUntil: event.target.checked ? '' : draft.unavailableUntil })} /><span>Доступен</span></label>
            {!draft.isAvailable && <label><span>Недоступен до</span><input type="date" value={draft.unavailableUntil} onChange={(event) => setDraft({ ...draft, unavailableUntil: event.target.value })} /></label>}
            <div className="product-supplier-form-actions"><button className="primary-action" disabled={busy} type="submit">{busy ? 'Сохраняем…' : 'Сохранить'}</button><button className="secondary-action" disabled={busy} type="button" onClick={() => setEditing(null)}>Отмена</button></div>
          </form>
        )}
        {loading && <p className="page-state">Загружаем поставщиков…</p>}
        {!loading && relations.length === 0 && <p className="page-state">{showArchive ? 'Архивных связей нет' : 'Поставщики ещё не добавлены'}</p>}
        <div className="product-supplier-cards">
          {relations.map((relation) => (
            <article key={relation.id} className={!relation.is_active ? 'is-archived' : ''}>
              <div className="product-supplier-card-title"><strong>{relation.supplier.display_name}</strong><span>{relation.role === 'PRIMARY' ? 'Основной' : 'Резервный'}{!relation.is_active ? ' · Архив' : ''}</span></div>
              {(relation.supplier_product_name || relation.supplier_sku) && <p>{relation.supplier_product_name || 'Название не указано'}{relation.supplier_sku ? ` · арт. ${relation.supplier_sku}` : ''}</p>}
              <dl><div><dt>Упаковка</dt><dd>{relation.package_unit.name_ru}: {relation.package_quantity} {relation.base_unit.short_name_ru}</dd></div><div><dt>Цена упаковки</dt><dd>{money(relation.price_per_package)}</dd></div><div><dt>За базовую единицу</dt><dd>{money(relation.price_per_base_unit)}{relation.price_per_base_unit ? ` / ${relation.base_unit.short_name_ru}` : ''}</dd></div><div><dt>Доступность</dt><dd>{relation.is_available ? 'Доступен' : `Недоступен${relation.unavailable_until ? ` до ${new Date(`${relation.unavailable_until}T00:00:00`).toLocaleDateString('ru-RU')}` : ''}`}</dd></div></dl>
              <div className="product-supplier-card-actions">
                <button type="button" className="secondary-action" disabled={busy} onClick={() => void toggleHistory(relation)}>{historyRelationId === relation.id ? 'Скрыть историю' : 'История цен'}</button>
                {relation.is_active ? <><button type="button" className="secondary-action" disabled={busy} onClick={() => beginEdit(relation)}>Изменить</button>{relation.role !== 'PRIMARY' && <button type="button" className="secondary-action" disabled={busy} onClick={() => void act(relation, 'primary')}>Назначить основным</button>}<button type="button" className="danger-action" disabled={busy} onClick={() => void act(relation, 'archive')}>Архивировать</button></> : <button type="button" className="primary-action" disabled={busy} onClick={() => void act(relation, 'restore')}>Восстановить</button>}
              </div>
              {historyRelationId === relation.id && (
                <section className="product-supplier-price-history" aria-label={`История цен: ${relation.supplier.display_name}`}>
                  {historyLoading && <p>Загружаем историю цен…</p>}
                  {historyError && <p className="request-message request-message-error" role="alert">{historyError}</p>}
                  {!historyLoading && !historyError && history.length === 0 && <p>История цен пока отсутствует</p>}
                  {!historyLoading && !historyError && history.length > 0 && (
                    <ol>
                      {history.map((item) => (
                        <li key={item.id}>
                          <time dateTime={item.effective_from}>{historyDate(item.effective_from)}</time>
                          <strong>{money(item.price_per_package)} / {item.package_quantity} {item.base_unit.short_name_ru}</strong>
                          <span>{money(item.base_unit_price_snapshot)} / {item.base_unit.short_name_ru}</span>
                          <small>{item.package_unit.name_ru} · {item.source === 'MANUAL' ? 'Вручную' : item.source}</small>
                        </li>
                      ))}
                    </ol>
                  )}
                </section>
              )}
            </article>
          ))}
        </div>
      </section>
    </div>
  )
}
