import { useEffect, useState, type FormEvent } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EosSelect } from '../components/EosFormControls'
import { useAuth } from '../contexts/AuthContext'
import {
  createWorkRequestComment,
  getWorkRequest,
  getWorkRequestAttachmentUrl,
  getWorkRequestComments,
  updateWorkRequest,
  type RepairPriority,
  type WorkRequest,
  type WorkRequestAttachment,
  type WorkRequestComment,
  type WorkRequestStatus,
} from '../services/requests'
import {
  DEPARTMENTS,
  PRIORITIES,
  REPAIR_CATEGORIES,
  REQUEST_STATUSES,
  priorityLabel,
  statusLabel,
} from './workRequestLogic'

function formatDate(value: string): string {
  return new Intl.DateTimeFormat('ru-RU', {
    dateStyle: 'long',
    timeStyle: 'short',
  }).format(new Date(value))
}

function AttachmentPreview({
  requestId,
  attachment,
}: {
  requestId: number
  attachment: WorkRequestAttachment
}) {
  const [url, setUrl] = useState('')

  useEffect(() => {
    let active = true
    let objectUrl = ''
    getWorkRequestAttachmentUrl(requestId, attachment.id)
      .then((nextUrl) => {
        objectUrl = nextUrl
        if (active) setUrl(nextUrl)
        else URL.revokeObjectURL(nextUrl)
      })
      .catch(() => setUrl(''))
    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [attachment.id, requestId])

  if (!url) {
    return <div className="attachment-loading">Загружаем фото…</div>
  }

  return (
    <a href={url} target="_blank" rel="noreferrer">
      <img src={url} alt={attachment.original_filename} />
      <span>{attachment.original_filename}</span>
    </a>
  )
}

function WorkRequestDetailPage() {
  const { requestId } = useParams()
  const numericRequestId = Number(requestId)
  const hasValidRequestId =
    Number.isInteger(numericRequestId) && numericRequestId > 0
  const { user } = useAuth()
  const [state, setState] = useState<'loading' | 'ready' | 'error'>(
    hasValidRequestId ? 'loading' : 'error',
  )
  const [request, setRequest] = useState<WorkRequest | null>(null)
  const [department, setDepartment] = useState('')
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [priority, setPriority] = useState('')
  const [status, setStatus] = useState<WorkRequestStatus>('new')
  const [isSaving, setIsSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState('')
  const [saveError, setSaveError] = useState('')
  const [comments, setComments] = useState<WorkRequestComment[]>([])
  const [commentsError, setCommentsError] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const [isCommenting, setIsCommenting] = useState(false)

  useEffect(() => {
    if (!hasValidRequestId) return
    getWorkRequest(numericRequestId)
      .then((item) => {
        if (item.request_type !== 'repair') {
          setState('error')
          return
        }
        setRequest(item)
        setDepartment(item.department)
        setDescription(item.description)
        setCategory(item.repair_category ?? '')
        setPriority(item.priority ?? '')
        setStatus(item.status)
        setState('ready')
        getWorkRequestComments(item.id)
          .then(setComments)
          .catch(() =>
            setCommentsError('Не удалось загрузить комментарии'),
          )
      })
      .catch(() => setState('error'))
  }, [hasValidRequestId, numericRequestId])

  async function saveChanges(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!request || isSaving) return
    setIsSaving(true)
    setSaveMessage('')
    setSaveError('')

    try {
      const updated = await updateWorkRequest(request.id, {
        department,
        description: description.trim(),
        status,
        repair_category: category,
        priority: priority as RepairPriority,
      })
      setRequest(updated)
      setSaveMessage('Изменения сохранены')
    } catch {
      setSaveError('Не удалось сохранить изменения')
    } finally {
      setIsSaving(false)
    }
  }

  async function addComment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const body = commentBody.trim()
    if (!request || !body || isCommenting) return
    setIsCommenting(true)
    setCommentsError('')
    try {
      const created = await createWorkRequestComment(request.id, body)
      setComments((current) => [...current, created])
      setCommentBody('')
    } catch {
      setCommentsError('Не удалось добавить комментарий')
    } finally {
      setIsCommenting(false)
    }
  }

  if (state === 'loading') {
    return <p className="page-state">Загружаем заявку…</p>
  }
  if (state === 'error' || !request) {
    return (
      <section className="request-page">
        <p className="request-message request-message-error">
          Заявка не найдена или недоступна
        </p>
        <Link className="request-back-link" to="/dashboard">
          ← На Dashboard
        </Link>
      </section>
    )
  }

  return (
    <section className="request-page request-detail-page">
      <div className="request-panel">
        <div className="request-heading">
          <div>
            <p className="eyebrow">Заявка на ремонт</p>
            <h1>Заявка №{request.id}</h1>
          </div>
          <Link className="request-back-link" to="/requests/repair">
            ← К списку
          </Link>
        </div>

        <dl className="request-facts">
          <div><dt>Подразделение</dt><dd>{request.department}</dd></div>
          <div><dt>Отправитель</dt><dd>{request.created_by_name}</dd></div>
          <div><dt>Создана</dt><dd>{formatDate(request.created_at)}</dd></div>
          <div><dt>Изменена</dt><dd>{formatDate(request.updated_at)}</dd></div>
          <div><dt>Статус</dt><dd>{statusLabel(request.status)}</dd></div>
          <div>
            <dt>Категория</dt>
            <dd>
              {request.repair_category}
            </dd>
          </div>
          <div><dt>Приоритет</dt><dd>{priorityLabel(request.priority)}</dd></div>
        </dl>

        {!user?.is_admin && (
          <section className="request-description">
            <h2>Описание</h2>
            <p>{request.description}</p>
          </section>
        )}

        {user?.is_admin && (
          <form
            className="request-form request-edit-form"
            onSubmit={(event) => void saveChanges(event)}
          >
            <label className="request-field">
              <span>Подразделение</span>
              <EosSelect
                value={department}
                disabled={isSaving}
                onChange={(event) => setDepartment(event.target.value)}
              >
                {DEPARTMENTS.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </EosSelect>
            </label>
            <label className="request-field">
              <span>Статус</span>
              <EosSelect
                value={status}
                disabled={isSaving}
                onChange={(event) =>
                  setStatus(event.target.value as WorkRequestStatus)
                }
              >
                {REQUEST_STATUSES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </EosSelect>
            </label>
            <label className="request-field">
              <span>Категория</span>
              <EosSelect
                value={category}
                disabled={isSaving}
                onChange={(event) => setCategory(event.target.value)}
              >
                {REPAIR_CATEGORIES.map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </EosSelect>
            </label>
            <label className="request-field">
              <span>Приоритет</span>
              <EosSelect
                value={priority}
                disabled={isSaving}
                onChange={(event) => setPriority(event.target.value)}
              >
                {PRIORITIES.map((item) => (
                  <option key={item.value} value={item.value}>
                    {item.label}
                  </option>
                ))}
              </EosSelect>
            </label>
            <label className="request-field request-field-wide">
              <span>Описание</span>
              <textarea
                value={description}
                maxLength={5000}
                required
                disabled={isSaving}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            {saveMessage && (
              <p className="request-message request-message-success">
                {saveMessage}
              </p>
            )}
            {saveError && (
              <p className="request-message request-message-error">
                {saveError}
              </p>
            )}
            <button
              className="primary-action request-submit"
              type="submit"
              disabled={isSaving || !description.trim()}
            >
              {isSaving ? 'Сохраняем…' : 'Сохранить изменения'}
            </button>
          </form>
        )}

        <>
            <section className="request-detail-section">
              <h2>Фотографии</h2>
              {request.attachments.length === 0 ? (
                <p className="page-state">Фотографии не приложены</p>
              ) : (
                <div className="attachment-grid">
                  {request.attachments.map((attachment) => (
                    <AttachmentPreview
                      key={attachment.id}
                      requestId={request.id}
                      attachment={attachment}
                    />
                  ))}
                </div>
              )}
            </section>

            <section className="request-detail-section">
              <h2>Комментарии</h2>
              {comments.length === 0 && !commentsError && (
                <p className="page-state">Комментариев пока нет</p>
              )}
              <div className="request-comments">
                {comments.map((comment) => (
                  <article key={comment.id}>
                    <p>{comment.body}</p>
                    <small>
                      {comment.author_name} · {formatDate(comment.created_at)}
                    </small>
                  </article>
                ))}
              </div>
              {commentsError && (
                <p className="request-message request-message-error">
                  {commentsError}
                </p>
              )}
              {user?.is_admin && (
                <form
                  className="comment-form"
                  onSubmit={(event) => void addComment(event)}
                >
                  <label className="request-field">
                    <span>Добавить комментарий</span>
                    <textarea
                      value={commentBody}
                      maxLength={2000}
                      disabled={isCommenting}
                      placeholder="Что происходит с заявкой?"
                      onChange={(event) => setCommentBody(event.target.value)}
                    />
                  </label>
                  <button
                    className="primary-action"
                    type="submit"
                    disabled={isCommenting || !commentBody.trim()}
                  >
                    {isCommenting ? 'Добавляем…' : 'Добавить комментарий'}
                  </button>
                </form>
              )}
            </section>
        </>
      </div>
    </section>
  )
}

export default WorkRequestDetailPage
