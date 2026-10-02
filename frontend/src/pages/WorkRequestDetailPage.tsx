import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  createWorkRequestComment, getRepairContractors, getRepairSpecializations,
  addRepairPhoto,
  getRepairTimeline, getWorkRequest, getWorkRequestAttachmentUrl,
  getWorkRequestComments, repairAction,
  updateRepairDetails,
  type RepairContractor, type RepairSpecialization, type RepairTimelineEvent,
  type WorkRequest, type WorkRequestAttachment, type WorkRequestComment,
} from '../services/requests'
import { PRIORITIES, REPAIR_CATEGORIES, priorityLabel, statusLabel } from './workRequestLogic'
import { EosSelect } from '../components/EosFormControls'

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'long', timeStyle: 'short' }).format(new Date(value))
}

function contractorSpecializations(contractorId: string, contractors: RepairContractor[], specializations: RepairSpecialization[]) {
  const ids = contractors.find((item) => item.id === contractorId)?.specialization_ids ?? []
  return specializations.filter((item) => item.is_active && ids.includes(item.id))
}

function selectedSpecialization(current: string, contractorId: string, contractors: RepairContractor[], specializations: RepairSpecialization[]) {
  const available = contractorSpecializations(contractorId, contractors, specializations)
  if (available.some((item) => item.id === current)) return current
  return available.length === 1 ? available[0].id : ''
}

function Photo({ requestId, attachment }: { requestId: number; attachment: WorkRequestAttachment }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let alive = true
    let objectUrl = ''
    getWorkRequestAttachmentUrl(requestId, attachment.id).then((value) => {
      objectUrl = value
      if (alive) setUrl(value)
      else URL.revokeObjectURL(value)
    }).catch(() => setUrl(''))
    return () => { alive = false; if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [requestId, attachment.id])
  return url ? <a href={url} target="_blank" rel="noreferrer"><img src={url} alt={attachment.original_filename} /><span>{attachment.original_filename}</span></a> : <span>Загружаем фото…</span>
}

function WorkRequestDetailPage() {
  const requestId = Number(useParams().requestId)
  const [repair, setRepair] = useState<WorkRequest | null>(null)
  const [comments, setComments] = useState<WorkRequestComment[]>([])
  const [events, setEvents] = useState<RepairTimelineEvent[]>([])
  const [contractors, setContractors] = useState<RepairContractor[]>([])
  const [specializations, setSpecializations] = useState<RepairSpecialization[]>([])
  const [contractorId, setContractorId] = useState('')
  const [specializationId, setSpecializationId] = useState('')
  const [visitAt, setVisitAt] = useState('')
  const [reason, setReason] = useState('')
  const [comment, setComment] = useState('')
  const [editDescription, setEditDescription] = useState('')
  const [editCategory, setEditCategory] = useState('')
  const [editPriority, setEditPriority] = useState<'routine' | 'important' | 'urgent'>('routine')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function reload() {
    const [item, nextComments, nextEvents] = await Promise.all([
      getWorkRequest(requestId), getWorkRequestComments(requestId), getRepairTimeline(requestId),
    ])
    setRepair(item)
    setComments(nextComments)
    setEvents(nextEvents)
    setEditDescription(item.description)
    setEditCategory(item.repair_category ?? '')
    setEditPriority(item.priority ?? 'routine')
    if (item.allowed_actions.includes('assign_contractor') || item.allowed_actions.includes('schedule_external_visit')) {
      const [nextContractors, nextSpecializations] = await Promise.all([
        getRepairContractors(), getRepairSpecializations(),
      ])
      setContractors(nextContractors)
      setSpecializations(nextSpecializations)
      setSpecializationId((current) => selectedSpecialization(
        current, item.contractor_id ?? contractorId, nextContractors, nextSpecializations,
      ))
    }
  }

  useEffect(() => {
    if (!Number.isInteger(requestId) || requestId <= 0) return
    let alive = true
    Promise.all([getWorkRequest(requestId), getWorkRequestComments(requestId), getRepairTimeline(requestId)])
      .then(([item, nextComments, nextEvents]) => {
        if (!alive) return
        setRepair(item)
        setComments(nextComments)
        setEvents(nextEvents)
        setContractorId(item.contractor_id ?? '')
        setSpecializationId(item.specialization_id ?? '')
        setEditDescription(item.description)
        setEditCategory(item.repair_category ?? '')
        setEditPriority(item.priority ?? 'routine')
        if (item.allowed_actions.includes('assign_contractor') || item.allowed_actions.includes('schedule_external_visit')) {
          Promise.all([getRepairContractors(), getRepairSpecializations()]).then(([nextContractors, nextSpecializations]) => {
            if (!alive) return
            setContractors(nextContractors); setSpecializations(nextSpecializations)
            setSpecializationId((current) => selectedSpecialization(
              current, item.contractor_id ?? '', nextContractors, nextSpecializations,
            ))
          }).catch(() => {})
        }
      }).catch(() => { if (alive) setError('Ремонт не найден или недоступен') })
    return () => { alive = false }
  }, [requestId])

  async function run(action: 'take' | 'assign-contractor' | 'schedule-external-visit' | 'escalate-to-supply' | 'close' | 'reopen', body?: object) {
    if (!repair || busy) return
    setBusy(true)
    setError('')
    try {
      await repairAction(repair.id, action, body)
      await reload()
      if (action === 'reopen') setReason('')
    } catch {
      setError('Не удалось выполнить действие. Обновите карточку и проверьте данные.')
    } finally { setBusy(false) }
  }

  async function addComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!repair || !comment.trim() || busy) return
    setBusy(true)
    setError('')
    try {
      await createWorkRequestComment(repair.id, comment.trim())
      setComment('')
      await reload()
    } catch { setError('Не удалось добавить комментарий') }
    finally { setBusy(false) }
  }

  async function saveDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!repair || busy || !editDescription.trim() || !editCategory) return
    setBusy(true); setError('')
    try {
      await updateRepairDetails(repair.id, { description: editDescription.trim(), repair_category: editCategory, priority: editPriority })
      await reload()
    } catch { setError('Не удалось сохранить описание ремонта') }
    finally { setBusy(false) }
  }

  if (!repair) return <section className="request-page"><p className="page-state">{error || 'Загружаем ремонт…'}</p></section>
  const can = (action: string) => repair.allowed_actions.includes(action)
  const availableSpecializations = contractorSpecializations(contractorId, contractors, specializations)

  return <section className="request-page request-detail-page"><div className="request-panel">
    <div className="request-heading"><div><p className="eyebrow">РЕМОНТ</p><h1>Заявка №{repair.id}</h1></div><Link className="request-back-link" to="/requests/repair">← К списку</Link></div>
    <dl className="request-facts">
      <div><dt>Подразделение</dt><dd>{repair.department}</dd></div>
      <div><dt>Инициатор</dt><dd>{repair.created_by_name}</dd></div>
      <div><dt>Создана</dt><dd>{formatDate(repair.created_at)}</dd></div>
      <div><dt>Статус</dt><dd>{statusLabel(repair.status)}</dd></div>
      <div><dt>Ответственный контур</dt><dd>{repair.responsible_role === 'HANDYMAN' ? 'Мастер по ремонту' : repair.responsible_role === 'SUPPLY_MANAGER' ? 'Руководитель снабжения' : 'Историческая заявка'}</dd></div>
      {repair.responsible_employee_name && <div><dt>Исполнитель</dt><dd>{repair.responsible_employee_name}</dd></div>}
      {repair.responsibility_started_at && <div><dt>Ответственность с</dt><dd>{formatDate(repair.responsibility_started_at)}</dd></div>}
      <div><dt>Категория</dt><dd>{repair.repair_category}</dd></div>
      <div><dt>Приоритет</dt><dd>{priorityLabel(repair.priority)}</dd></div>
      {repair.visit_at && <div><dt>Визит мастера</dt><dd>{formatDate(repair.visit_at)}</dd></div>}
      {repair.contractor_id && <div><dt>Подрядчик</dt><dd>{repair.contractor_name} · {repair.contractor_phone}{repair.specialization_name ? ` · ${repair.specialization_name}` : ''}</dd></div>}
    </dl>
    <section className="request-description"><h2>Описание</h2><p>{repair.description}</p></section>
    {can('edit_details') && <section className="request-detail-section"><h2>Уточнить заявку</h2><form className="request-form" onSubmit={(event) => void saveDetails(event)}>
      <label className="request-field"><span>Категория</span><select value={editCategory} disabled={busy} onChange={(event) => setEditCategory(event.target.value)}>{REPAIR_CATEGORIES.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
      <label className="request-field"><span>Приоритет</span><select value={editPriority} disabled={busy} onChange={(event) => setEditPriority(event.target.value as 'routine' | 'important' | 'urgent')}>{PRIORITIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
      <label className="request-field request-field-wide"><span>Описание</span><textarea value={editDescription} maxLength={5000} required disabled={busy} onChange={(event) => setEditDescription(event.target.value)} /></label>
      <button className="primary-action" type="submit" disabled={busy || !editDescription.trim()}>Сохранить изменения</button>
    </form></section>}
    <section className="request-detail-section"><h2>Фотографии</h2>{repair.attachments.length ? <div className="attachment-grid">{repair.attachments.map((item) => <Photo key={item.id} requestId={repair.id} attachment={item} />)}</div> : <p className="page-state">Фотографий нет</p>}</section>
    {can('add_photo') && <label className="request-field"><span>Добавить фотографию</span><input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={(event) => {
      const file = event.target.files?.[0]
      if (!file || busy) return
      if (file.size > 8 * 1024 * 1024) { setError('Фотография должна быть не больше 8 МБ'); return }
      setBusy(true); setError('')
      addRepairPhoto(repair.id, file).then(() => reload()).catch(() => setError('Не удалось добавить фотографию')).finally(() => setBusy(false))
      event.target.value = ''
    }} /></label>}
    {(can('take') || can('close') || can('escalate_to_supply')) && <section className="request-detail-section"><h2>Действия</h2>
      {can('take') && <button type="button" className="primary-action" disabled={busy} onClick={() => void run('take')}>Взять в работу</button>}
      {can('close') && <button type="button" className="primary-action" disabled={busy} onClick={() => void run('close')}>Закрыть ремонт</button>}
      {can('escalate_to_supply') && <button type="button" className="primary-action" disabled={busy} onClick={() => void run('escalate-to-supply')}>Не смог назначить время — передать руководителю</button>}
    </section>}
    {(can('assign_contractor') || can('schedule_external_visit')) && <section className="request-detail-section"><h2>Внешний мастер</h2><div className="request-form">
      <label className="request-field"><span>Подрядчик</span><EosSelect value={contractorId} disabled={busy} onChange={(event) => { const nextId = event.target.value; setContractorId(nextId); setSpecializationId(selectedSpecialization('', nextId, contractors, specializations)) }}><option value="">Выберите подрядчика</option>{contractors.filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.phone}</option>)}</EosSelect></label>
      <label className="request-field"><span>Специализация</span><EosSelect value={specializationId} disabled={busy || !contractorId || availableSpecializations.length === 0} onChange={(event) => setSpecializationId(event.target.value)}><option value="">Выберите специализацию</option>{availableSpecializations.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</EosSelect>{contractorId && availableSpecializations.length === 0 && <small className="field-error">У подрядчика нет активных специализаций</small>}</label>
      <label className="request-field"><span>Время визита</span><input type="datetime-local" value={visitAt} disabled={busy} onChange={(event) => setVisitAt(event.target.value)} /></label>
      {can('assign_contractor') && <button type="button" disabled={busy || !contractorId || !specializationId} onClick={() => void run('assign-contractor', { contractor_id: contractorId, specialization_id: specializationId })}>Нужен внешний мастер · сохранить подрядчика</button>}
      {can('schedule_external_visit') && <button type="button" className="primary-action" disabled={busy || !contractorId || !specializationId || !visitAt} onClick={() => void run('schedule-external-visit', { contractor_id: contractorId, specialization_id: specializationId, visit_at: new Date(visitAt).toISOString() })}>Мастер придёт</button>}
    </div></section>}
    {can('reopen') && <section className="request-detail-section"><h2>Не приняли результат?</h2><label className="request-field"><span>Причина переоткрытия</span><textarea value={reason} maxLength={1000} disabled={busy} onChange={(event) => setReason(event.target.value)} /></label><button type="button" className="primary-action" disabled={busy || !reason.trim()} onClick={() => void run('reopen', { reason: reason.trim() })}>Переоткрыть</button></section>}
    <section className="request-detail-section"><h2>История</h2>{events.length ? <div className="request-comments">{events.map((item, index) => <article key={`${item.at}-${index}`}><p>{item.details}{item.reason ? `: ${item.reason}` : ''}</p><small>{item.actor || 'Система'} · {formatDate(item.at)}{item.role ? ` · ${item.role}` : ''}</small></article>)}</div> : <p className="page-state">Для старой заявки история действий не записывалась</p>}</section>
    <section className="request-detail-section"><h2>Комментарии</h2><div className="request-comments">{comments.map((item) => <article key={item.id}><p>{item.body}</p><small>{item.author_name} · {formatDate(item.created_at)}</small></article>)}</div>{can('comment') && <form className="comment-form" onSubmit={(event) => void addComment(event)}><label className="request-field"><span>Добавить комментарий</span><textarea value={comment} maxLength={2000} disabled={busy} onChange={(event) => setComment(event.target.value)} /></label><button className="primary-action" type="submit" disabled={busy || !comment.trim()}>Добавить комментарий</button></form>}</section>
    {error && <p className="request-message request-message-error">{error}</p>}
  </div></section>
}

export default WorkRequestDetailPage
