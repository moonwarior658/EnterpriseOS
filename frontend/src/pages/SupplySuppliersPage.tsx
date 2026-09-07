import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { EosPagination, EosSearchField } from '../components/EosFormControls'
import {
  archiveSupplySupplier,
  getSupplySuppliers,
  restoreSupplySupplier,
  type SupplySupplier,
} from '../services/supplyAdmin'
import SupplySupplierForm from './SupplySupplierForm'
import { supplierErrorMessage } from './supplySupplierLogic'
import './SupplySuppliersPage.css'

const PAGE_SIZE = 50

function SupplySuppliersPage() {
  const [items, setItems] = useState<SupplySupplier[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [active, setActive] = useState(true)
  const [search, setSearch] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busySupplierId, setBusySupplierId] = useState<string | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [formSupplier, setFormSupplier] = useState<SupplySupplier | null>(null)
  const activeRequest = useRef<AbortController | null>(null)

  const loadSuppliers = useCallback(async () => {
    activeRequest.current?.abort()
    const controller = new AbortController()
    activeRequest.current = controller
    setIsLoading(true)
    setError('')
    try {
      const page = await getSupplySuppliers(
        active,
        search,
        offset,
        PAGE_SIZE,
        controller.signal,
      )
      if (controller.signal.aborted) return
      setItems(page.items)
      setTotal(page.total)
    } catch (requestError) {
      if (controller.signal.aborted) return
      setError(supplierErrorMessage(
        requestError,
        'Не удалось загрузить поставщиков',
      ))
    } finally {
      if (!controller.signal.aborted) setIsLoading(false)
    }
  }, [active, offset, search])

  useEffect(() => {
    const timeout = window.setTimeout(() => void loadSuppliers(), 250)
    return () => {
      window.clearTimeout(timeout)
      activeRequest.current?.abort()
    }
  }, [loadSuppliers])

  function selectState(nextActive: boolean) {
    setActive(nextActive)
    setOffset(0)
    setFormOpen(false)
    setFormSupplier(null)
    setNotice('')
  }

  function openCreateForm() {
    setFormSupplier(null)
    setFormOpen(true)
    setError('')
    setNotice('')
  }

  function openSupplier(supplier: SupplySupplier) {
    setFormSupplier(supplier)
    setFormOpen(true)
    setError('')
    setNotice('')
  }

  async function archiveSupplier(supplier: SupplySupplier) {
    if (!window.confirm(`Архивировать поставщика «${supplier.display_name}»?`)) {
      return
    }
    setBusySupplierId(supplier.id)
    setError('')
    setNotice('')
    try {
      await archiveSupplySupplier(supplier.id)
      setFormOpen(false)
      setFormSupplier(null)
      setNotice('Поставщик перемещён в архив')
      await loadSuppliers()
    } catch (requestError) {
      setError(supplierErrorMessage(
        requestError,
        'Не удалось архивировать поставщика',
      ))
    } finally {
      setBusySupplierId(null)
    }
  }

  async function restoreSupplier(supplier: SupplySupplier) {
    setBusySupplierId(supplier.id)
    setError('')
    setNotice('')
    try {
      await restoreSupplySupplier(supplier.id)
      setFormOpen(false)
      setFormSupplier(null)
      setNotice('Поставщик восстановлен')
      await loadSuppliers()
    } catch (requestError) {
      setError(supplierErrorMessage(
        requestError,
        'Не удалось восстановить поставщика',
      ))
    } finally {
      setBusySupplierId(null)
    }
  }

  function handleSaved(saved: SupplySupplier, created: boolean) {
    setFormOpen(false)
    setFormSupplier(null)
    setNotice(created ? 'Поставщик создан' : 'Изменения сохранены')
    if (saved.is_active !== active) {
      setActive(saved.is_active)
      setOffset(0)
    } else {
      void loadSuppliers()
    }
  }

  return (
    <section className="request-page supply-admin-page supplier-page">
      <div className="request-panel">
        <div className="request-heading supplier-page-heading">
          <div>
            <p className="eyebrow">СНАБЖЕНИЕ · СПРАВОЧНИКИ</p>
            <h1>Поставщики</h1>
            <p className="subtitle">
              Контакты и реквизиты поставщиков компании
            </p>
          </div>
          <div className="supplier-heading-actions">
            <Link className="request-back-link" to="/supply/requests">
              К заявкам →
            </Link>
            <button
              className="primary-action"
              type="button"
              disabled={formOpen}
              onClick={openCreateForm}
            >
              Добавить поставщика
            </button>
          </div>
        </div>

        <div className="supplier-toolbar">
          <div className="iiko-mapping-tabs" role="tablist" aria-label="Статус">
            <button
              className={active ? 'is-active' : ''}
              type="button"
              role="tab"
              aria-selected={active}
              disabled={formOpen}
              onClick={() => selectState(true)}
            >
              Активные
            </button>
            <button
              className={!active ? 'is-active' : ''}
              type="button"
              role="tab"
              aria-selected={!active}
              disabled={formOpen}
              onClick={() => selectState(false)}
            >
              Архив
            </button>
          </div>
          <EosSearchField
            label="Поиск"
            value={search}
            placeholder="Название или ИНН"
            maxLength={240}
            onChange={(event) => {
              setSearch(event.target.value)
              setOffset(0)
            }}
          />
        </div>

        {formOpen && (
          <SupplySupplierForm
            key={formSupplier?.id ?? 'create'}
            supplier={formSupplier}
            onCancel={() => {
              setFormOpen(false)
              setFormSupplier(null)
            }}
            onSaved={handleSaved}
          />
        )}

        {error && (
          <p className="request-message request-message-error" role="alert">
            {error}
          </p>
        )}
        {notice && (
          <p className="request-message request-message-success" role="status">
            {notice}
          </p>
        )}

        <div className="supplier-table-wrap">
          <table className="supplier-table">
            <thead>
              <tr>
                <th>Название</th>
                <th>Юридическое название</th>
                <th>ИНН</th>
                <th>Телефон</th>
                <th>Email заказов</th>
                <th>Статус</th>
                <th aria-label="Действия" />
              </tr>
            </thead>
            <tbody>
              {isLoading && (
                <tr><td className="supplier-table-state" colSpan={7}>
                  Загружаем поставщиков…
                </td></tr>
              )}
              {!isLoading && items.length === 0 && (
                <tr><td className="supplier-table-state" colSpan={7}>
                  {active
                    ? 'Активных поставщиков по выбранным условиям нет'
                    : 'Архивных поставщиков по выбранным условиям нет'}
                </td></tr>
              )}
              {!isLoading && items.map((supplier) => (
                <tr key={supplier.id}>
                  <td><strong>{supplier.display_name}</strong></td>
                  <td>{supplier.legal_name ?? '—'}</td>
                  <td>{supplier.inn ?? '—'}</td>
                  <td>
                    {supplier.phone
                      ? <a href={`tel:${supplier.phone}`}>{supplier.phone}</a>
                      : '—'}
                  </td>
                  <td>
                    {supplier.order_email
                      ? <a href={`mailto:${supplier.order_email}`}>
                          {supplier.order_email}
                        </a>
                      : '—'}
                  </td>
                  <td>
                    <span className={
                      supplier.is_active
                        ? 'badge badge-active'
                        : 'badge badge-blocked'
                    }>
                      {supplier.is_active ? 'Активен' : 'Архивирован'}
                    </span>
                  </td>
                  <td>
                    <div className="supplier-row-actions">
                      <button
                        className="secondary-action"
                        type="button"
                        disabled={formOpen || busySupplierId === supplier.id}
                        onClick={() => openSupplier(supplier)}
                      >
                        Открыть
                      </button>
                      {supplier.is_active ? (
                        <button
                          className="secondary-action"
                          type="button"
                          disabled={formOpen || busySupplierId === supplier.id}
                          onClick={() => void archiveSupplier(supplier)}
                        >
                          Архивировать
                        </button>
                      ) : (
                        <button
                          className="secondary-action"
                          type="button"
                          disabled={formOpen || busySupplierId === supplier.id}
                          onClick={() => void restoreSupplier(supplier)}
                        >
                          Восстановить
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {!isLoading && (
          <EosPagination
            offset={offset}
            total={total}
            pageSize={PAGE_SIZE}
            itemCount={items.length}
            onPageChange={setOffset}
          />
        )}
      </div>
    </section>
  )
}

export default SupplySuppliersPage
