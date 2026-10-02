import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { EosDateField, EosSelect } from '../components/EosFormControls'
import { BusinessActionError, createEmployeeSupplyRequest } from '../services/actionContext'
import { getSupplyCycles, getSupplyDepartments, getSupplyDirections, type SupplyCycle, type SupplyReference } from '../services/supplyAdmin'
import { useSupplyPermissions } from '../services/useSupplyPermissions'
import './SupplyPurchaseRequestsPage.css'

export default function SupplyRequestCreatePage() {
  const navigate = useNavigate()
  const { context, canCreateRequest } = useSupplyPermissions()
  const [departments, setDepartments] = useState<SupplyReference[]>([])
  const [directions, setDirections] = useState<SupplyReference[]>([])
  const [cycles, setCycles] = useState<SupplyCycle[]>([])
  const [departmentId, setDepartmentId] = useState('')
  const [directionId, setDirectionId] = useState('')
  const [cycleId, setCycleId] = useState('')
  const [needDate, setNeedDate] = useState('')
  const [multilineText, setMultilineText] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const sellerOnly = Boolean(context?.roles.includes('SELLER') && !context.roles.some((role) =>
    ['ADMIN', 'SUPPLY_MANAGER', 'NETWORK_MANAGER', 'HEAD_OF_PRODUCTION', 'CHEF_CONFECTIONER'].includes(role)))

  useEffect(() => {
    Promise.all([getSupplyDepartments(), getSupplyDirections(), getSupplyCycles()])
      .then(([departmentRows, directionRows, cyclePage]) => {
        setDepartments(departmentRows)
        setDirections(directionRows)
        setCycles(cyclePage.items)
        setDepartmentId((current) => current || departmentRows[0]?.id || '')
        setDirectionId((current) => current || directionRows[0]?.id || '')
      })
      .catch(() => setMessage('Не удалось загрузить данные для заявки'))
      .finally(() => setLoading(false))
  }, [])

  const availableCycles = cycles.filter((cycle) => cycle.direction_id === directionId && cycle.status === 'OPEN')
  const selectedCycle = availableCycles.some((cycle) => cycle.id === cycleId) ? cycleId : availableCycles[0]?.id ?? ''
  const effectiveDepartment = sellerOnly ? context?.actual_department_id ?? '' : departmentId

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !canCreateRequest || !effectiveDepartment || !directionId || !selectedCycle || !multilineText.trim()) return
    setBusy(true); setMessage('')
    try {
      const created = await createEmployeeSupplyRequest({
        department_id: effectiveDepartment, direction_id: directionId,
        cycle_id: selectedCycle, need_date: needDate || null,
        multiline_text: multilineText,
      })
      navigate(`/supply/requests/${created.id}`)
    } catch (error) {
      setMessage(error instanceof BusinessActionError ? error.message : 'Не удалось создать заявку')
    } finally { setBusy(false) }
  }

  return <section className="request-page supply-admin-page purchase-request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">СНАБЖЕНИЕ</p><h1>Новая заявка</h1></div><Link className="request-back-link" to="/supply/requests">К заявкам →</Link></div>
    {loading ? <p className="page-state">Загружаем данные…</p> : !canCreateRequest ? <p className="page-state">Для создания заявки требуется разрешённая роль и, для продавца, активная смена.</p> : <form onSubmit={submit}>
      <div className="purchase-request-header">
        <label className="eos-field"><span>Подразделение</span><EosSelect value={effectiveDepartment} disabled={busy || sellerOnly} onChange={(event) => setDepartmentId(event.target.value)}><option value="">Выберите подразделение</option>{departments.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</EosSelect></label>
        <label className="eos-field"><span>Направление</span><EosSelect value={directionId} disabled={busy} onChange={(event) => { setDirectionId(event.target.value); setCycleId('') }}><option value="">Выберите направление</option>{directions.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</EosSelect></label>
        <label className="eos-field"><span>Цикл заявок</span><EosSelect value={selectedCycle} disabled={busy} onChange={(event) => setCycleId(event.target.value)}><option value="">Выберите цикл</option>{availableCycles.map((item) => <option key={item.id} value={item.id}>{item.cycle_date}</option>)}</EosSelect></label>
        <EosDateField label="Дата потребности" value={needDate} disabled={busy} onChange={(event) => setNeedDate(event.target.value)} />
      </div>
      <label className="eos-field"><span>Что требуется (каждая позиция с новой строки)</span><textarea value={multilineText} disabled={busy} rows={8} maxLength={10000} onChange={(event) => setMultilineText(event.target.value)} /></label>
      {!availableCycles.length && <p className="request-message">Для выбранного направления нет открытого цикла заявок.</p>}
      {message && <p className="request-message" role="alert">{message}</p>}
      <div className="purchase-actions"><button className="primary-action" type="submit" disabled={busy || !effectiveDepartment || !directionId || !selectedCycle || !multilineText.trim()}>{busy ? 'Создаём…' : 'Создать заявку'}</button></div>
    </form>}
  </div></section>
}
