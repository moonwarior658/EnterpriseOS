import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { EosCheckbox } from '../components/EosFormControls'
import {
  createRepairContractor, createRepairSpecialization, getContractorHistory,
  getRepairContractors, getRepairSpecializations, updateRepairContractor,
  type ContractorHistory, type RepairContractor, type RepairSpecialization,
} from '../services/requests'
import { statusLabel } from './workRequestLogic'

function RepairContractorsPage() {
  const [contractors, setContractors] = useState<RepairContractor[]>([])
  const [specializations, setSpecializations] = useState<RepairSpecialization[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [editing, setEditing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [notes, setNotes] = useState('')
  const [priceNotes, setPriceNotes] = useState('')
  const [specializationIds, setSpecializationIds] = useState<string[]>([])
  const [showNewSpecialization, setShowNewSpecialization] = useState(false)
  const [newSpecialization, setNewSpecialization] = useState('')
  const [reason, setReason] = useState('')
  const [history, setHistory] = useState<ContractorHistory[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const selected = contractors.find((item) => item.id === selectedId) ?? null
  const names = useMemo(() => new Map(specializations.map((item) => [item.id, item.name])), [specializations])
  const summary = useMemo(() => ({
    total: history.length,
    closed: history.filter((item) => item.status === 'completed').length,
    reopened: history.filter((item) => item.reopened).length,
  }), [history])

  async function reload() {
    const [nextContractors, nextSpecializations] = await Promise.all([
      getRepairContractors(), getRepairSpecializations(),
    ])
    setContractors(nextContractors); setSpecializations(nextSpecializations)
  }

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      void reload().catch(() => setError('Не удалось загрузить справочник'))
    }, 0)
    return () => window.clearTimeout(timeout)
  }, [])

  async function open(item: RepairContractor) {
    setSelectedId(item.id); setEditing(false); setCreating(false); setError(''); setReason('')
    setName(item.name); setPhone(item.phone); setNotes(item.notes ?? '')
    setPriceNotes(item.price_notes ?? ''); setSpecializationIds(item.specialization_ids)
    try { setHistory(await getContractorHistory(item.id)) }
    catch { setError('Не удалось загрузить историю подрядчика') }
  }

  function startCreate() {
    setSelectedId(''); setHistory([]); setName(''); setPhone(''); setNotes(''); setPriceNotes('')
    setSpecializationIds([]); setReason(''); setCreating(true); setEditing(true)
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !name.trim() || !phone.trim()) return
    setBusy(true); setError('')
    try {
      const input = { name: name.trim(), phone: phone.trim(), notes: notes.trim() || null,
        price_notes: priceNotes.trim() || null, specialization_ids: specializationIds }
      if (selectedId) await updateRepairContractor(selectedId, input)
      else await createRepairContractor(input)
      await reload(); setCreating(false); setEditing(false); setSelectedId('')
    } catch { setError('Не удалось сохранить подрядчика. Проверьте поля и повторите действие.') }
    finally { setBusy(false) }
  }

  async function changeActive() {
    if (!selected || !reason.trim() || busy) return
    setBusy(true); setError('')
    try {
      await updateRepairContractor(selected.id, { is_active: !selected.is_active, reason: reason.trim() })
      await reload(); setReason('')
    } catch { setError('Не удалось изменить состояние подрядчика') }
    finally { setBusy(false) }
  }

  async function addSpecialization(event: FormEvent) {
    event.preventDefault()
    if (!newSpecialization.trim() || busy) return
    setBusy(true); setError('')
    try {
      const created = await createRepairSpecialization(newSpecialization.trim())
      await reload(); setSpecializationIds((current) => [...new Set([...current, created.id])])
      setNewSpecialization(''); setShowNewSpecialization(false)
    } catch { setError('Не удалось добавить специализацию') }
    finally { setBusy(false) }
  }

  const form = <form className="request-form contractor-form" onSubmit={(event) => void save(event)}>
    <label className="request-field"><span>ФИО или компания</span><input value={name} maxLength={240} disabled={busy} required onChange={(event) => setName(event.target.value)} /></label>
    <label className="request-field"><span>Телефон</span><input value={phone} maxLength={64} disabled={busy} required onChange={(event) => setPhone(event.target.value)} /></label>
    <label className="request-field request-field-wide"><span>Комментарий</span><textarea value={notes} maxLength={2000} disabled={busy} onChange={(event) => setNotes(event.target.value)} /></label>
    <label className="request-field request-field-wide"><span>Прайс / условия</span><textarea value={priceNotes} maxLength={4000} disabled={busy} placeholder="Например: выезд 2 000 ₽, далее по согласованию" onChange={(event) => setPriceNotes(event.target.value)} /></label>
    <div className="request-field request-field-wide contractor-specializations"><div className="contractor-field-heading"><span>Специализации</span><button className="secondary-action contractor-add-specialization" type="button" aria-label="Добавить специализацию" onClick={() => setShowNewSpecialization((value) => !value)}>+</button></div>
      <div className="contractor-multiselect">{specializations.filter((item) => item.is_active || specializationIds.includes(item.id)).map((item) => <EosCheckbox key={item.id} label={item.name} checked={specializationIds.includes(item.id)} disabled={busy || !item.is_active} onChange={(event) => setSpecializationIds((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} />)}</div>
      {showNewSpecialization && <div className="contractor-inline-create"><input aria-label="Название специализации" value={newSpecialization} maxLength={120} autoFocus onChange={(event) => setNewSpecialization(event.target.value)} /><button className="primary-action" type="button" disabled={!newSpecialization.trim() || busy} onClick={(event) => void addSpecialization(event)}>Добавить</button></div>}
    </div>
    <div className="user-actions"><button className="primary-action" disabled={busy || !name.trim() || !phone.trim()} type="submit">{busy ? 'Сохраняем…' : 'Сохранить'}</button><button className="secondary-action" type="button" disabled={busy} onClick={() => { setCreating(false); setEditing(false) }}>Отмена</button></div>
  </form>

  return <section className="request-page"><div className="request-panel contractor-page">
    <div className="request-heading"><div><p className="eyebrow">РЕМОНТ</p><h1>Внешние подрядчики</h1></div><Link className="request-back-link" to="/requests/repair">← К ремонтам</Link></div>
    {error && <p className="request-message request-message-error">{error}</p>}
    <button className="primary-action" type="button" onClick={startCreate}>+ Добавить подрядчика</button>
    {creating && <section className="request-detail-section"><h2>Новый подрядчик</h2>{form}</section>}
    <section className="request-detail-section"><h2>Каталог</h2><div className="contractor-catalog">
      {contractors.map((item) => <button key={item.id} type="button" className="contractor-card" onClick={() => void open(item)}><span className="contractor-card-heading"><strong>{item.name}</strong><b className={`badge ${item.is_active ? 'badge-active' : ''}`}>{item.is_active ? 'Активен' : 'Неактивен'}</b></span><span>{item.phone}</span><span>{item.specialization_ids.map((id) => names.get(id)).filter(Boolean).join(', ') || 'Специализации не указаны'}</span>{item.notes && <small>{item.notes}</small>}</button>)}
    </div></section>
    {selected && <section className="request-detail-section contractor-detail"><div className="employee-section-heading"><h2>{selected.name}</h2><button className="secondary-action" type="button" onClick={() => setEditing((value) => !value)}>{editing ? 'Отмена' : 'Редактировать'}</button></div>
      {editing ? form : <><dl className="employee-facts"><div><dt>Телефон</dt><dd>{selected.phone}</dd></div><div><dt>Статус</dt><dd>{selected.is_active ? 'Активен' : 'Неактивен'}</dd></div><div><dt>Специализации</dt><dd>{selected.specialization_ids.map((id) => names.get(id)).filter(Boolean).join(', ') || '—'}</dd></div><div><dt>Комментарий</dt><dd>{selected.notes || '—'}</dd></div><div><dt>Прайс / условия</dt><dd className="preserve-lines">{selected.price_notes || '—'}</dd></div></dl>
        <div className="contractor-state-action"><label className="request-field"><span>Причина изменения состояния</span><textarea value={reason} maxLength={1000} onChange={(event) => setReason(event.target.value)} /></label><button className={selected.is_active ? 'danger-action' : 'primary-action'} type="button" disabled={busy || !reason.trim()} onClick={() => void changeActive()}>{selected.is_active ? 'Деактивировать' : 'Активировать'}</button></div></>}
      <div className="contractor-history-summary"><span>Всего ремонтов: <strong>{summary.total}</strong></span><span>Закрыто: <strong>{summary.closed}</strong></span><span>Переоткрыто: <strong>{summary.reopened}</strong></span></div>
      <div className="request-comments">{history.map((item) => <article key={item.repair_id}><strong>Ремонт №{item.repair_id}</strong><p>{new Date(item.created_at).toLocaleDateString('ru-RU')} · {item.department} · {item.category} · {statusLabel(item.status)}</p><p>{item.description}</p>{item.visit_at && <small>Визит: {new Date(item.visit_at).toLocaleString('ru-RU')}</small>}{item.closed_at && <small>Закрыт: {new Date(item.closed_at).toLocaleString('ru-RU')}</small>}{item.reopened && <b className="badge">Переоткрывался</b>}<Link to={`/requests/${item.repair_id}`}>Открыть ремонт</Link></article>)}</div>
    </section>}
  </div></section>
}

export default RepairContractorsPage
