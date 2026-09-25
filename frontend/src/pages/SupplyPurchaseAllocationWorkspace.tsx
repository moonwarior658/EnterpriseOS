import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  confirmSupplyPurchaseAllocation,
  createSupplyPurchaseAllocation,
  deleteSupplyPurchaseAllocation,
  getSupplyPurchaseAllocations,
  updateSupplyPurchaseAllocation,
  updateSupplyPurchaseAllocationSources,
  createSupplySupplierOrders,
  type SupplySupplierOrder,
  type SupplyPurchaseAllocationWorkspace as Workspace,
  SupplyApiError,
} from '../services/supplyAdmin'
import {
  coverageLabel,
  minimumOrderLabel,
  suggestedPackages,
} from './supplyPurchaseAllocationLogic'


const money = new Intl.NumberFormat('ru-RU', { style: 'currency', currency: 'RUB' })

export default function SupplyPurchaseAllocationWorkspace({ requestId }: { requestId: string }) {
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [busyKey, setBusyKey] = useState('')
  const [message, setMessage] = useState('')
  const [orders, setOrders] = useState<SupplySupplierOrder[]>([])
  const [sourceValues, setSourceValues] = useState<Record<string, string>>({})

  useEffect(() => {
    const controller = new AbortController()
    getSupplyPurchaseAllocations(requestId, controller.signal)
      .then(setWorkspace)
      .catch(() => { if (!controller.signal.aborted) setMessage('Не удалось загрузить распределение') })
    return () => controller.abort()
  }, [requestId])

  async function mutate(key: string, action: () => Promise<Workspace>) {
    setBusyKey(key); setMessage('')
    try { setWorkspace(await action()) }
    catch (error) { setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось сохранить распределение') }
    finally { setBusyKey('') }
  }

  async function createOrders() {
    setBusyKey('orders'); setMessage('')
    try {
      const result = await createSupplySupplierOrders(requestId)
      setOrders(result.orders)
      setMessage(result.orders.length ? 'Заказы сформированы' : 'Нет подтверждённых распределений для формирования')
    } catch (error) {
      setMessage(error instanceof SupplyApiError ? error.message : 'Не удалось сформировать заказы')
    } finally { setBusyKey('') }
  }

  function sourceValue(allocationId: string, sourceId: string, fallback: string) {
    return sourceValues[`${allocationId}:${sourceId}`] ?? fallback
  }

  if (!workspace) return <p className="page-state">{message || 'Загружаем поставщиков…'}</p>

  return <div className="allocation-workspace">
    {!workspace.lines.some((line) => line.allocations.length > 0) && <p className="page-state">Распределение ещё не выполнено</p>}
    <div className="allocation-summary">
      <div><span>Плановая стоимость</span><strong>{money.format(Number(workspace.planned_total_amount))}</strong></div>
      {workspace.supplier_subtotals.map((subtotal) => <div
        className={subtotal.minimum_order_status === 'BELOW_MINIMUM' ? 'allocation-summary-warning' : ''}
        key={subtotal.supplier_id}
      >
        <span>{subtotal.supplier_display_name} · {subtotal.allocation_count} поз.</span>
        <strong>Итого: {money.format(Number(subtotal.planned_total_amount))}</strong>
        <small>{minimumOrderLabel(
          subtotal,
          (value) => money.format(Number(value)),
        )}</small>
      </div>)}
    </div>
    {workspace.lines.some((line) => line.allocations.some((allocation) => allocation.status === 'CONFIRMED')) && <div className="purchase-actions"><button type="button" className="primary-action" disabled={busyKey !== ''} onClick={createOrders}>Сформировать заказы</button></div>}
    {orders.length > 0 && <div className="allocation-summary">{orders.map((order) => <div key={order.id}><span>{order.supplier_display_name}</span><strong><Link to={`/supply/supplier-orders/${order.id}`}>{order.number}</Link></strong><small>{money.format(Number(order.total_amount))} · {order.status === 'DRAFT' ? 'Черновик' : order.status === 'READY' ? 'Готов' : 'Отменён'}</small></div>)}</div>}
    {message && <p className="request-message">{message}</p>}
    {workspace.lines.map((line) => <article className="allocation-line" key={line.line_id}>
      <header>
        <div><h3>{line.product_name}</h3><p>Потребность: {line.required_quantity} {line.unit.short_name_ru}</p></div>
        <div className={Number(line.overallocated_quantity) > 0 ? 'allocation-coverage over' : 'allocation-coverage'}>
          <strong>{line.allocated_quantity} / {line.required_quantity} {line.unit.short_name_ru}</strong>
          <span>{coverageLabel(line.remaining_quantity, line.overallocated_quantity)} {line.unit.short_name_ru}</span>
        </div>
      </header>
      {!line.eligible_suppliers.length && !line.allocations.length && <p className="page-state">Нет доступных поставщиков с совместимой единицей и полной ценой.</p>}
      <div className="allocation-suppliers">{line.eligible_suppliers.map((supplier) => {
        const allocation = line.allocations.find((item) => item.product_supplier_id === supplier.product_supplier_id)
        const count = counts[supplier.product_supplier_id] ?? allocation?.packages_count ?? suggestedPackages(line.remaining_quantity, supplier.package_quantity)
        const readOnly = allocation?.status === 'CONFIRMED'
        const packageQuantity = allocation?.package_quantity_snapshot ?? supplier.package_quantity
        const packagePrice = allocation?.price_per_package_snapshot ?? supplier.price_per_package
        const basePrice = allocation?.base_unit_price_snapshot ?? supplier.base_unit_price
        const quantity = readOnly ? allocation.quantity_base : String(count * Number(packageQuantity))
        const amount = readOnly ? allocation.planned_amount : String(count * Number(packagePrice))
        return <section className="allocation-supplier" key={supplier.product_supplier_id}>
          <div className="allocation-supplier-title"><strong>{supplier.supplier_display_name}</strong><span>{supplier.role === 'PRIMARY' ? 'Основной' : 'Резервный'}</span></div>
          <p>{packageQuantity} {supplier.package_unit.short_name_ru} / уп. · {money.format(Number(packagePrice))} / уп.</p>
          <p>{money.format(Number(basePrice))} / {supplier.package_unit.short_name_ru}</p>
          {allocation?.current_terms_changed && <p className="allocation-warning">Текущая цена или фасовка поставщика изменилась. Сохранён прежний план.</p>}
          <div className="allocation-counter">
            <button type="button" disabled={readOnly || busyKey !== '' || count <= 1} onClick={() => setCounts({ ...counts, [supplier.product_supplier_id]: count - 1 })}>−</button>
            <input aria-label={`Упаковки ${supplier.supplier_display_name}`} type="number" min="1" step="1" value={count} disabled={readOnly || busyKey !== ''} onChange={(event) => setCounts({ ...counts, [supplier.product_supplier_id]: Math.max(1, Math.trunc(Number(event.target.value) || 1)) })} />
            <button type="button" disabled={readOnly || busyKey !== ''} onClick={() => setCounts({ ...counts, [supplier.product_supplier_id]: count + 1 })}>+</button>
            <span>{count} уп. = {quantity} {line.unit.short_name_ru}</span>
          </div>
          <strong className="allocation-amount">{money.format(Number(amount))}</strong>
          {allocation && <div className="purchase-source-group">
            <strong>Распределение по источникам</strong>
            {allocation.sources.map((source) => <label className="eos-field" key={source.purchase_request_line_source_id}>
              <span>{source.source_type === 'MANUAL_FUTURE' ? 'Будущая потребность' : source.source_label}{source.need_date ? ` · ${source.need_date}` : ''}</span>
              <small>Нужно {source.required_quantity}; уже распределено {source.already_allocated_quantity}; осталось {source.remaining_quantity} {line.unit.short_name_ru}</small>
              <input aria-label={`Источник ${source.source_label}`} type="number" min="0" step="0.000001" disabled={readOnly || busyKey !== '' || allocation.sources.length === 1} value={sourceValue(allocation.id, source.purchase_request_line_source_id, source.allocated_quantity)} onChange={(event) => setSourceValues({ ...sourceValues, [`${allocation.id}:${source.purchase_request_line_source_id}`]: event.target.value })} />
            </label>)}
            {(() => {
              const target = Math.min(Number(quantity), allocation.sources.reduce((sum, source) => sum + Number(source.remaining_quantity), 0))
              const distributed = allocation.sources.reduce((sum, source) => sum + Number(sourceValue(allocation.id, source.purchase_request_line_source_id, source.allocated_quantity)), 0)
              const left = Math.max(target - distributed, 0)
              return <><p>Осталось распределить: {left} {line.unit.short_name_ru}</p><p>Покрыто источниками: {distributed}; излишек фасовки: {Math.max(Number(quantity) - distributed, 0)} {line.unit.short_name_ru}</p>{allocation.status === 'DRAFT' && allocation.sources.length > 1 && <button type="button" className="secondary-action" disabled={busyKey !== '' || Math.abs(left) > 0.000001 || distributed > target + 0.000001} onClick={() => mutate(allocation.id, () => updateSupplyPurchaseAllocationSources(requestId, line.line_id, allocation.id, allocation.sources.filter((source) => Number(sourceValue(allocation.id, source.purchase_request_line_source_id, source.allocated_quantity)) > 0).map((source) => ({ purchase_request_line_source_id: source.purchase_request_line_source_id, allocated_quantity: sourceValue(allocation.id, source.purchase_request_line_source_id, source.allocated_quantity) }))))}>Сохранить распределение</button>}</>
            })()}
            {allocation.traceability_status === 'UNTRACEABLE_LEGACY' && <p className="allocation-warning">Для legacy-распределения происхождение количества неизвестно.</p>}
          </div>}
          <div className="supplier-row-actions">
            {!allocation && <button type="button" className="primary-action" disabled={busyKey !== ''} onClick={() => mutate(supplier.product_supplier_id, () => createSupplyPurchaseAllocation(requestId, line.line_id, supplier.product_supplier_id, count))}>Добавить</button>}
            {allocation?.status === 'DRAFT' && <><button type="button" className="secondary-action" disabled={busyKey !== ''} onClick={() => mutate(allocation.id, () => updateSupplyPurchaseAllocation(requestId, line.line_id, allocation.id, count))}>Сохранить</button><button type="button" className="primary-action" disabled={busyKey !== '' || allocation.traceability_status !== 'TRACEABLE'} onClick={() => mutate(allocation.id, () => confirmSupplyPurchaseAllocation(requestId, line.line_id, allocation.id))}>Подтвердить</button><button type="button" className="danger-action" disabled={busyKey !== ''} onClick={() => mutate(allocation.id, () => deleteSupplyPurchaseAllocation(requestId, line.line_id, allocation.id))}>Удалить</button></>}
            {readOnly && <span className="purchase-status purchase-status-ready">Подтверждено</span>}
          </div>
        </section>
      })}</div>
      {line.allocations.filter((allocation) => !line.eligible_suppliers.some((supplier) => supplier.product_supplier_id === allocation.product_supplier_id)).map((allocation) => <section className="allocation-supplier allocation-ineligible" key={allocation.id}><strong>{allocation.supplier_display_name}</strong><p>{allocation.packages_count} уп. · {allocation.quantity_base} {line.unit.short_name_ru} · {money.format(Number(allocation.planned_amount))}</p><p className="allocation-warning">Поставщик больше недоступен для редактирования или подтверждения. Snapshot сохранён.</p><div className="supplier-row-actions">{allocation.status === 'DRAFT' ? <button type="button" className="danger-action" disabled={busyKey !== ''} onClick={() => mutate(allocation.id, () => deleteSupplyPurchaseAllocation(requestId, line.line_id, allocation.id))}>Удалить</button> : <span className="purchase-status purchase-status-ready">Подтверждено</span>}</div></section>)}
    </article>)}
  </div>
}
