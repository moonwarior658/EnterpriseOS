import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import {
  createRepairContractor, createRepairSpecialization, getContractorHistory,
  getRepairContractors, getRepairSpecializations, updateRepairContractor,
  updateRepairSpecialization, type ContractorHistory, type RepairContractor,
  type RepairSpecialization,
} from '../services/requests'
import { statusLabel } from './workRequestLogic'

function RepairContractorsPage() {
  const [contractors, setContractors] = useState<RepairContractor[]>([])
  const [specializations, setSpecializations] = useState<RepairSpecialization[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [name, setName] = useState('')
  const [phone, setPhone] = useState('')
  const [notes, setNotes] = useState('')
  const [specializationIds, setSpecializationIds] = useState<string[]>([])
  const [newSpecialization, setNewSpecialization] = useState('')
  const [specializationReason, setSpecializationReason] = useState('')
  const [reason, setReason] = useState('')
  const [history, setHistory] = useState<ContractorHistory[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function reload() {
    const [nextContractors, nextSpecializations] = await Promise.all([
      getRepairContractors(), getRepairSpecializations(),
    ])
    setContractors(nextContractors)
    setSpecializations(nextSpecializations)
  }
  useEffect(() => {
    let active = true
    Promise.all([getRepairContractors(), getRepairSpecializations()])
      .then(([nextContractors, nextSpecializations]) => {
        if (!active) return
        setContractors(nextContractors)
        setSpecializations(nextSpecializations)
      }).catch(() => { if (active) setError('Не удалось загрузить справочник') })
    return () => { active = false }
  }, [])

  function select(item: RepairContractor | null) {
    setSelectedId(item?.id ?? '')
    setName(item?.name ?? '')
    setPhone(item?.phone ?? '')
    setNotes(item?.notes ?? '')
    setSpecializationIds(item?.specialization_ids ?? [])
    setReason('')
    setHistory([])
    if (item) getContractorHistory(item.id).then(setHistory).catch(() => setError('Не удалось загрузить историю подрядчика'))
  }

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !name.trim() || !phone.trim()) return
    setBusy(true); setError('')
    try {
      const input = { name: name.trim(), phone: phone.trim(), notes: notes.trim() || null, specialization_ids: specializationIds }
      if (selectedId) await updateRepairContractor(selectedId, input)
      else await createRepairContractor(input)
      await reload()
      select(null)
    } catch { setError('Не удалось сохранить подрядчика. Проверьте поля и повторите действие.') }
    finally { setBusy(false) }
  }

  async function changeActive(isActive: boolean) {
    if (!selectedId || !reason.trim() || busy) return
    setBusy(true); setError('')
    try {
      await updateRepairContractor(selectedId, { is_active: isActive, reason: reason.trim() })
      await reload(); select(null)
    } catch { setError('Не удалось изменить состояние подрядчика') }
    finally { setBusy(false) }
  }

  async function addSpecialization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!newSpecialization.trim() || busy) return
    setBusy(true); setError('')
    try {
      await createRepairSpecialization(newSpecialization.trim())
      setNewSpecialization(''); await reload()
    } catch { setError('Не удалось добавить специализацию') }
    finally { setBusy(false) }
  }

  async function changeSpecializationActive(item: RepairSpecialization) {
    if (busy || !specializationReason.trim()) return
    setBusy(true); setError('')
    try {
      await updateRepairSpecialization(item.id, { is_active: !item.is_active, reason: specializationReason.trim() })
      setSpecializationReason(''); await reload()
    } catch { setError('Не удалось изменить состояние специализации') }
    finally { setBusy(false) }
  }

  return <section className="request-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">РЕМОНТ</p><h1>Внешние подрядчики</h1></div><Link className="request-back-link" to="/requests/repair">← К ремонтам</Link></div>
    {error && <p className="request-message request-message-error">{error}</p>}
    <section className="request-detail-section"><h2>Подрядчики</h2><div className="work-request-list">
      {contractors.map((item) => <button key={item.id} type="button" className="work-request-row" onClick={() => select(item)}><strong>{item.name}</strong><span>{item.phone} · {item.is_active ? 'Активен' : 'Неактивен'}</span></button>)}
    </div></section>
    <section className="request-detail-section"><h2>{selectedId ? 'Изменить подрядчика' : 'Новый подрядчик'}</h2>
      <form className="request-form" onSubmit={(event) => void save(event)}>
        <label className="request-field"><span>Имя или компания</span><input value={name} maxLength={240} disabled={busy} required onChange={(event) => setName(event.target.value)} /></label>
        <label className="request-field"><span>Телефон</span><input value={phone} maxLength={64} disabled={busy} required onChange={(event) => setPhone(event.target.value)} /></label>
        <label className="request-field request-field-wide"><span>Примечание</span><textarea value={notes} maxLength={2000} disabled={busy} onChange={(event) => setNotes(event.target.value)} /></label>
        <fieldset className="request-field request-field-wide"><legend>Специализации</legend>{specializations.filter((item) => item.is_active).map((item) => <label key={item.id}><input type="checkbox" checked={specializationIds.includes(item.id)} disabled={busy} onChange={(event) => setSpecializationIds((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /> {item.name}</label>)}</fieldset>
        <button className="primary-action" disabled={busy || !name.trim() || !phone.trim()} type="submit">{busy ? 'Сохраняем…' : 'Сохранить подрядчика'}</button>
        {selectedId && <button type="button" disabled={busy} onClick={() => select(null)}>Очистить форму</button>}
      </form>
      {selectedId && <div className="request-form"><label className="request-field"><span>Причина изменения состояния</span><textarea value={reason} disabled={busy} onChange={(event) => setReason(event.target.value)} /></label><button type="button" disabled={busy || !reason.trim()} onClick={() => void changeActive(!contractors.find((item) => item.id === selectedId)?.is_active)}>{contractors.find((item) => item.id === selectedId)?.is_active ? 'Деактивировать' : 'Активировать'}</button></div>}
    </section>
    <section className="request-detail-section"><h2>Специализации</h2><form className="request-form" onSubmit={(event) => void addSpecialization(event)}><label className="request-field"><span>Новая специализация</span><input value={newSpecialization} maxLength={120} disabled={busy} onChange={(event) => setNewSpecialization(event.target.value)} /></label><button className="primary-action" disabled={busy || !newSpecialization.trim()} type="submit">Добавить</button></form>
      <label className="request-field"><span>Причина изменения состояния специализации</span><input value={specializationReason} maxLength={1000} disabled={busy} onChange={(event) => setSpecializationReason(event.target.value)} /></label>
      <div className="request-comments">{specializations.map((item) => <article key={item.id}><p>{item.name} · {item.is_active ? 'Активна' : 'Неактивна'}</p><button type="button" disabled={busy || !specializationReason.trim()} onClick={() => void changeSpecializationActive(item)}>{item.is_active ? 'Деактивировать' : 'Активировать'}</button></article>)}</div>
    </section>
    {selectedId && <section className="request-detail-section"><h2>Связанные ремонты</h2><div className="request-comments">{history.map((item) => <article key={item.repair_id}><Link to={`/requests/${item.repair_id}`}>Ремонт №{item.repair_id}</Link><p>{item.department} · {item.specialization || 'Специализация не указана'} · {statusLabel(item.status)}</p>{item.visit_at && <small>Визит: {new Date(item.visit_at).toLocaleString('ru-RU')}</small>}</article>)}</div></section>}
  </div></section>
}

export default RepairContractorsPage
