import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  EosCheckbox,
  EosPagination,
  EosSearchField,
  EosSelect,
} from '../components/EosFormControls'
import {
  getSupplyDepartments,
  getSupplyProducts,
  getSupplyUnits,
  type SupplyProduct,
  type SupplyReference,
  type SupplyUnit,
} from '../services/supplyAdmin'
import {
  bootstrapIikoProductCatalog,
  confirmProductMapping,
  confirmUnitMapping,
  confirmWarehouseMapping,
  generateMappingCandidates,
  getProductMappings,
  getUnitMappings,
  getWarehouseMappings,
  ignoreMapping,
  IikoMappingApiError,
  mappingQuery,
  syncIikoReferenceData,
  unmapMapping,
  type IikoMappingKind,
  type IikoMappingStatus,
  type IikoLegalContour,
  type IikoCatalogBootstrapResult,
  type IikoProductMapping,
  type IikoReferenceSyncResult,
  type IikoUnitMapping,
  type IikoWarehouseMapping,
  type IikoWarehouseDestinationType,
  type IikoWarehouseRole,
} from '../services/iikoMapping'
import {
  iikoMappingStatusLabel,
  iikoWarehouseDestinationTypeLabel,
  iikoWarehouseRoleLabel,
  iikoLegalContourLabel,
  mappingActionLabel,
} from './iikoMappingLogic'


type MappingItem =
  | IikoProductMapping
  | IikoUnitMapping
  | IikoWarehouseMapping

const ROLES: IikoWarehouseRole[] = [
  'MAIN', 'PACKAGING', 'HOUSEHOLD', 'FIXED_ASSETS', 'OTHER',
]
const DESTINATION_TYPES: IikoWarehouseDestinationType[] = [
  'DESTINATION', 'SOURCE',
]
const LEGAL_CONTOURS: IikoLegalContour[] = ['IP', 'OOO']
const PAGE_SIZE = 100

function withoutDraft<T>(
  current: Record<string, T>,
  mappingId: string,
): Record<string, T> {
  const next = { ...current }
  delete next[mappingId]
  return next
}

function IikoMappingPage() {
  const [tab, setTab] = useState<IikoMappingKind>('products')
  const [items, setItems] = useState<MappingItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [status, setStatus] = useState<IikoMappingStatus | ''>('')
  const [search, setSearch] = useState('')
  const [includeDeleted, setIncludeDeleted] = useState(false)
  const [conflictsOnly, setConflictsOnly] = useState(false)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState<string | null>(null)
  const [referenceReady, setReferenceReady] = useState(false)
  const [syncResult, setSyncResult] =
    useState<IikoReferenceSyncResult | null>(null)
  const [bootstrapResult, setBootstrapResult] =
    useState<IikoCatalogBootstrapResult | null>(null)
  const [products, setProducts] = useState<SupplyProduct[]>([])
  const [units, setUnits] = useState<SupplyUnit[]>([])
  const [departments, setDepartments] = useState<SupplyReference[]>([])
  const [targetDrafts, setTargetDrafts] = useState<Record<string, string>>({})
  const [roleDrafts, setRoleDrafts] = useState<
    Record<string, IikoWarehouseRole>
  >({})
  const [destinationTypeDrafts, setDestinationTypeDrafts] = useState<
    Record<string, IikoWarehouseDestinationType>
  >({})
  const [legalContourDrafts, setLegalContourDrafts] = useState<
    Record<string, IikoLegalContour>
  >({})

  const load = useCallback(async () => {
    setState('loading')
    setError('')
    const query = mappingQuery({
      status,
      search,
      includeDeleted,
      conflictsOnly,
      limit: PAGE_SIZE,
      offset,
    })
    try {
      const page = tab === 'products'
        ? await getProductMappings(query)
        : tab === 'units'
          ? await getUnitMappings(query)
          : await getWarehouseMappings(query)
      setItems(page.items)
      setTotal(page.total)
      setTargetDrafts((current) => {
        const next = { ...current }
        for (const item of page.items) {
          if (next[item.id] !== undefined) continue
          next[item.id] = tab === 'products'
            ? (item as IikoProductMapping).eos_product_id ?? ''
            : tab === 'units'
              ? (item as IikoUnitMapping).eos_unit_id ?? ''
              : (item as IikoWarehouseMapping).eos_department_id ?? ''
        }
        return next
      })
      if (tab === 'warehouses') {
        setDestinationTypeDrafts((current) => {
          const next = { ...current }
          for (const rawItem of page.items) {
            const item = rawItem as IikoWarehouseMapping
            if (next[item.id] === undefined) {
              next[item.id] = item.destination_type
            }
          }
          return next
        })
        setRoleDrafts((current) => {
          const next = { ...current }
          for (const rawItem of page.items) {
            const item = rawItem as IikoWarehouseMapping
            if (next[item.id] === undefined) {
              next[item.id] = item.role ?? 'OTHER'
            }
          }
          return next
        })
        setLegalContourDrafts((current) => {
          const next = { ...current }
          for (const rawItem of page.items) {
            const item = rawItem as IikoWarehouseMapping
            if (next[item.id] === undefined) {
              next[item.id] = item.legal_contour ?? 'IP'
            }
          }
          return next
        })
      }
      setState('ready')
    } catch (loadError) {
      setError(
        loadError instanceof IikoMappingApiError
          ? loadError.message
          : 'Не удалось загрузить mapping',
      )
      setState('error')
    }
  }, [conflictsOnly, includeDeleted, offset, search, status, tab])

  useEffect(() => {
    void Promise.all([
      getSupplyProducts(),
      getSupplyUnits(),
      getSupplyDepartments(),
    ]).then(([
      productPage,
      nextUnits,
      nextDepartments,
    ]) => {
      setProducts(productPage.items)
      setUnits(nextUnits)
      setDepartments(nextDepartments)
    }).catch(() => setError('Не удалось загрузить справочники EOS'))
  }, [])

  useEffect(() => {
    const timeout = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(timeout)
  }, [load])

  async function generate() {
    setBusyId('generate')
    setError('')
    try {
      await generateMappingCandidates()
      await load()
    } catch (actionError) {
      setError(
        actionError instanceof IikoMappingApiError
          ? actionError.message
          : 'Не удалось сформировать предложения',
      )
    } finally {
      setBusyId(null)
    }
  }

  async function bootstrapCatalog() {
    setBusyId('bootstrap-catalog')
    setError('')
    setBootstrapResult(null)
    try {
      const result = await bootstrapIikoProductCatalog()
      setBootstrapResult(result)
      const productPage = await getSupplyProducts()
      setProducts(productPage.items)
      await load()
    } catch (actionError) {
      setError(
        actionError instanceof IikoMappingApiError
          ? actionError.message
          : 'Не удалось создать каталог EOS из iiko',
      )
    } finally {
      setBusyId(null)
    }
  }

  async function syncReferenceData() {
    setBusyId('sync-reference')
    setError('')
    setSyncResult(null)
    setReferenceReady(false)
    try {
      const result = await syncIikoReferenceData()
      setSyncResult(result)
      setReferenceReady(true)
      await load()
    } catch {
      setError('Не удалось обновить данные iiko. Повторите попытку')
    } finally {
      setBusyId(null)
    }
  }

  async function confirm(item: MappingItem) {
    const targetId = targetDrafts[item.id]
    const warehouseDestinationType =
      destinationTypeDrafts[item.id] ?? 'DESTINATION'
    if (
      tab !== 'warehouses'
        ? !targetId
        : warehouseDestinationType === 'DESTINATION' && !targetId
    ) {
      setError('Выберите объект EOS')
      return
    }
    setBusyId(item.id)
    setError('')
    try {
      const replace = item.status === 'CONFIRMED'
      if (tab === 'products') {
        await confirmProductMapping(item.id, targetId, replace)
      } else if (tab === 'units') {
        await confirmUnitMapping(item.id, targetId, replace)
      } else {
        await confirmWarehouseMapping(
          item.id,
          warehouseDestinationType === 'DESTINATION'
            ? {
                destination_type: 'DESTINATION',
                eos_department_id: targetId,
                role: roleDrafts[item.id] ?? 'OTHER',
              }
            : {
                destination_type: 'SOURCE',
                legal_contour: legalContourDrafts[item.id] ?? 'IP',
                role: roleDrafts[item.id] ?? 'OTHER',
              },
          replace,
        )
      }
      await load()
    } catch (actionError) {
      setError(
        actionError instanceof IikoMappingApiError
          ? actionError.message
          : 'Не удалось сохранить mapping',
      )
    } finally {
      setBusyId(null)
    }
  }

  async function changeState(
    item: MappingItem,
    action: 'ignore' | 'unmap',
  ) {
    setBusyId(item.id)
    setError('')
    try {
      if (action === 'ignore') await ignoreMapping(tab, item.id)
      else await unmapMapping(tab, item.id)
      setTargetDrafts((current) => ({ ...current, [item.id]: '' }))
      setDestinationTypeDrafts((current) => withoutDraft(current, item.id))
      setRoleDrafts((current) => withoutDraft(current, item.id))
      setLegalContourDrafts((current) => withoutDraft(current, item.id))
      await load()
    } catch (actionError) {
      setError(
        actionError instanceof IikoMappingApiError
          ? actionError.message
          : 'Не удалось изменить mapping',
      )
    } finally {
      setBusyId(null)
    }
  }

  function targetOptions() {
    if (tab === 'products') {
      return products.map((item) => (
        <option key={item.id} value={item.id}>{item.name}</option>
      ))
    }
    if (tab === 'units') {
      return units.map((item) => (
        <option key={item.id} value={item.id}>{item.name_ru}</option>
      ))
    }
    return departments.map((item) => (
      <option key={item.id} value={item.id}>{item.name}</option>
    ))
  }

  return (
    <section className="request-page supply-admin-page iiko-mapping-page">
      <div className="request-panel">
        <div className="request-heading">
          <div>
            <p className="eyebrow">IIKO ↔ EOS</p>
            <h1>Явный mapping</h1>
            <p className="request-intro">
              Автоматические совпадения требуют подтверждения администратора.
            </p>
          </div>
          <Link className="request-back-link" to="/dashboard">← На Dashboard</Link>
        </div>

        <div className="iiko-mapping-toolbar">
          <div className="iiko-mapping-tabs" role="tablist">
            {([
              ['products', 'Товары'],
              ['units', 'Единицы'],
              ['warehouses', 'Склады'],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={tab === value}
                className={tab === value ? 'is-active' : ''}
                onClick={() => { setTab(value); setOffset(0) }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="iiko-mapping-toolbar-actions">
            <button
              type="button"
              className="secondary-action"
              disabled={busyId !== null}
              onClick={() => void syncReferenceData()}
            >
              {busyId === 'sync-reference'
                ? 'Обновляем данные iiko…'
                : 'Обновить данные iiko'}
            </button>
            {tab === 'products' && (
              <button
                type="button"
                className="secondary-action"
                disabled={busyId !== null || !referenceReady}
                onClick={() => void bootstrapCatalog()}
              >
                {busyId === 'bootstrap-catalog'
                  ? 'Создаём каталог EOS…'
                  : 'Создать каталог EOS из iiko'}
              </button>
            )}
            <button
              type="button"
              className="primary-action"
              disabled={busyId !== null || !referenceReady}
              onClick={() => void generate()}
            >
              {busyId === 'generate'
                ? 'Формируем предложения…'
                : 'Сформировать предложения'}
            </button>
          </div>
        </div>

        {syncResult && (
          <>
            <p className="request-message iiko-mapping-sync-result">
              Данные iiko обновлены: товары — {syncResult.products},
              {' '}единицы — {syncResult.units},
              {' '}склады — {syncResult.warehouses}.
            </p>
            {syncResult.warning && (
              <p className="request-message iiko-mapping-sync-warning">
                {syncResult.warning}
              </p>
            )}
          </>
        )}
        {bootstrapResult && (
          <p className="request-message iiko-mapping-sync-result">
            Каталог EOS обработан: created — {bootstrapResult.created},
            {' '}linked — {bootstrapResult.linked},
            {' '}existing — {bootstrapResult.existing},
            {' '}conflicts — {bootstrapResult.conflicts},
            {' '}skipped — {bootstrapResult.skipped}.
          </p>
        )}

        <div className="iiko-mapping-filters">
          <EosSearchField
            aria-label="Поиск mapping"
            placeholder="Название или код"
            value={search}
            onChange={(event) => {
              setSearch(event.target.value)
              setOffset(0)
            }}
          />
          <EosSelect
            aria-label="Статус mapping"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as IikoMappingStatus | '')
              setOffset(0)
            }}
          >
            <option value="">Все статусы</option>
            {([
              'UNMAPPED', 'SUGGESTED', 'CONFIRMED', 'CONFLICT', 'IGNORED',
            ] as IikoMappingStatus[]).map((value) => (
              <option key={value} value={value}>
                {iikoMappingStatusLabel(value)}
              </option>
            ))}
          </EosSelect>
          <EosCheckbox
            label="Показывать удалённые"
            checked={includeDeleted}
            onChange={(event) => {
              setIncludeDeleted(event.target.checked)
              setOffset(0)
            }}
          />
          <EosCheckbox
            label="Только конфликты"
            checked={conflictsOnly}
            onChange={(event) => {
              setConflictsOnly(event.target.checked)
              setOffset(0)
            }}
          />
        </div>

        {error && (
          <p className="request-message request-message-error">{error}</p>
        )}
        {state === 'loading' && <p className="page-state">Загружаем mapping…</p>}
        {state === 'ready' && items.length === 0 && (
          <p className="page-state">Позиций по выбранным условиям нет</p>
        )}
        {items.length > 0 && (
          <div className="iiko-mapping-list">
            <p className="request-intro">Найдено: {total}</p>
            {items.map((item) => (
              <article
                className={[
                  'iiko-mapping-row',
                  `status-${item.status.toLowerCase()}`,
                  tab === 'warehouses' ? 'is-warehouse' : '',
                ].filter(Boolean).join(' ')}
                key={item.id}
              >
                <div className="iiko-mapping-source">
                  <div className="iiko-mapping-source-heading">
                    <strong>{item.source_name}</strong>
                    <small>{iikoMappingStatusLabel(item.status)}</small>
                  </div>
                  <span>
                    {item.source_code || 'Без кода'}
                    {item.is_deleted ? ' · удалено в iiko' : ''}
                  </span>
                  {item.reasons.length > 0 && (
                    <p title={item.reasons.join(' · ')}>
                      {item.reasons.join(' · ')}
                    </p>
                  )}
                </div>
                <div className="iiko-mapping-target">
                  {tab === 'warehouses' && (
                    <EosSelect
                      aria-label={`Тип назначения склада ${item.source_name}`}
                      value={destinationTypeDrafts[item.id] ?? 'DESTINATION'}
                      onChange={(event) => setDestinationTypeDrafts(
                        (current) => ({
                          ...current,
                          [item.id]: event.target.value as
                            IikoWarehouseDestinationType,
                        }),
                      )}
                    >
                      {DESTINATION_TYPES.map((destinationType) => (
                        <option key={destinationType} value={destinationType}>
                          {iikoWarehouseDestinationTypeLabel(destinationType)}
                        </option>
                      ))}
                    </EosSelect>
                  )}
                  {(
                    tab !== 'warehouses'
                    || (destinationTypeDrafts[item.id] ?? 'DESTINATION')
                      === 'DESTINATION'
                  ) && (
                    <EosSelect
                      aria-label={`Объект EOS для ${item.source_name}`}
                      value={targetDrafts[item.id] ?? ''}
                      onChange={(event) => setTargetDrafts((current) => ({
                        ...current,
                        [item.id]: event.target.value,
                      }))}
                    >
                      <option value="">Выберите объект EOS</option>
                      {targetOptions()}
                    </EosSelect>
                  )}
                  {tab === 'warehouses' && (
                    <>
                      {(destinationTypeDrafts[item.id] ?? 'DESTINATION')
                        === 'DESTINATION' ? (
                          <>
                            <span className="iiko-mapping-contour">
                              Контур:{' '}
                              {departments.find(
                                (department) => department.id
                                  === targetDrafts[item.id],
                              )?.legal_contour ?? 'не настроен'}
                            </span>
                            <EosSelect
                              aria-label={`Роль склада ${item.source_name}`}
                              value={roleDrafts[item.id] ?? 'OTHER'}
                              onChange={(event) => setRoleDrafts((current) => ({
                                ...current,
                                [item.id]: event.target.value as
                                  IikoWarehouseRole,
                              }))}
                            >
                              {ROLES.map((role) => (
                                <option key={role} value={role}>
                                  {iikoWarehouseRoleLabel(role)}
                                </option>
                              ))}
                            </EosSelect>
                          </>
                        ) : (
                          <>
                            <EosSelect
                              aria-label={`Контур источника ${item.source_name}`}
                              value={legalContourDrafts[item.id] ?? 'IP'}
                              onChange={(event) => setLegalContourDrafts(
                                (current) => ({
                                  ...current,
                                  [item.id]: event.target.value as
                                    IikoLegalContour,
                                }),
                              )}
                            >
                              {LEGAL_CONTOURS.map((contour) => (
                                <option key={contour} value={contour}>
                                  {iikoLegalContourLabel(contour)}
                                </option>
                              ))}
                            </EosSelect>
                            <EosSelect
                              aria-label={`Роль склада ${item.source_name}`}
                              value={roleDrafts[item.id] ?? 'OTHER'}
                              onChange={(event) => setRoleDrafts((current) => ({
                                ...current,
                                [item.id]: event.target.value as
                                  IikoWarehouseRole,
                              }))}
                            >
                              {ROLES.map((role) => (
                                <option key={role} value={role}>
                                  {iikoWarehouseRoleLabel(role)}
                                </option>
                              ))}
                            </EosSelect>
                          </>
                        )}
                    </>
                  )}
                </div>
                <div className="iiko-mapping-actions">
                  <button
                    type="button"
                    className="primary-action"
                    disabled={busyId !== null}
                    onClick={() => void confirm(item)}
                  >
                    {mappingActionLabel(item.status)}
                  </button>
                  <button
                    type="button"
                    className="secondary-action"
                    disabled={busyId !== null}
                    onClick={() => void changeState(item, 'ignore')}
                  >
                    Игнорировать
                  </button>
                  <button
                    type="button"
                    className="secondary-action"
                    disabled={busyId !== null}
                    onClick={() => void changeState(item, 'unmap')}
                  >
                    Снять связь
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
        <EosPagination
          offset={offset}
          total={total}
          pageSize={PAGE_SIZE}
          itemCount={items.length}
          onPageChange={setOffset}
        />
      </div>
    </section>
  )
}

export default IikoMappingPage
