import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from 'react'
import {
  createPublicSupplyRequest,
  getPublicSupplyCycles,
  getPublicSupplyDepartments,
  getPublicSupplyRequest,
  PublicSupplyApiError,
  submitPublicSupplyRequest,
  updatePublicSupplyLines,
  type PublicSupplyCycle,
  type PublicSupplyDepartment,
  type PublicSupplyRequest,
} from '../services/publicSupply'
import {
  formatRemainingTime,
  hasBlockingDuplicates,
  hasUnrecognizedLines,
  PUBLIC_SUPPLY_MAX_TEXT_LENGTH,
  PUBLIC_SUPPLY_SESSION_KEY,
  publicSupplyFormError,
  remainingSeconds,
  requestLinesAsText,
} from './publicSupplyLogic'

const EXAMPLES = [
  'Картофель 10 кг',
  'Молоко 5 л',
  'Салфетки 3 уп',
  'Яйцо 30 шт',
]

function safeMessage(error: unknown): string {
  if (error instanceof PublicSupplyApiError) return error.message
  return 'Не удалось выполнить запрос. Попробуйте ещё раз'
}

function PublicSupplyRequestPage() {
  const [departments, setDepartments] = useState<PublicSupplyDepartment[]>([])
  const [cycles, setCycles] = useState<PublicSupplyCycle[]>([])
  const [departmentId, setDepartmentId] = useState('')
  const [cycleId, setCycleId] = useState('')
  const [authorName, setAuthorName] = useState('')
  const [authorPhone, setAuthorPhone] = useState('')
  const [multilineText, setMultilineText] = useState('')
  const [request, setRequest] = useState<PublicSupplyRequest | null>(null)
  const [publicToken, setPublicToken] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [confirmUnrecognized, setConfirmUnrecognized] = useState(false)
  const [isBusy, setIsBusy] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState('')
  const [receivedAtMs, setReceivedAtMs] = useState(0)
  const [clockMs, setClockMs] = useState(0)

  const applyRequest = useCallback((next: PublicSupplyRequest) => {
    setRequest(next)
    setReceivedAtMs(Date.now())
    setClockMs(Date.now())
  }, [])

  useEffect(() => {
    let active = true
    const storedToken = sessionStorage.getItem(PUBLIC_SUPPLY_SESSION_KEY)
    Promise.allSettled([
      getPublicSupplyDepartments(),
      storedToken ? getPublicSupplyRequest(storedToken) : Promise.resolve(null),
    ]).then(([departmentsResult, requestResult]) => {
      if (!active) return
      if (departmentsResult.status === 'fulfilled') {
        setDepartments(departmentsResult.value)
      } else {
        setError('Не удалось загрузить форму. Обновите страницу')
      }
      if (
        requestResult.status === 'fulfilled'
        && requestResult.value
        && storedToken
      ) {
        setPublicToken(storedToken)
        applyRequest(requestResult.value)
      }
      if (requestResult.status === 'rejected' && storedToken) {
        const caught: unknown = requestResult.reason
        if (
          caught instanceof PublicSupplyApiError
          && caught.code === 'SUPPLY_PUBLIC_REQUEST_NOT_FOUND'
        ) {
          sessionStorage.removeItem(PUBLIC_SUPPLY_SESSION_KEY)
        } else {
          setError('Не удалось восстановить заявку. Попробуйте ещё раз')
        }
      }
    }).catch(() => {
      if (active) {
        setError('Не удалось загрузить форму. Обновите страницу')
      }
    }).finally(() => {
      if (active) setIsLoading(false)
    })
    return () => {
      active = false
    }
  }, [applyRequest])

  useEffect(() => {
    if (!departmentId || request) return
    let active = true
    getPublicSupplyCycles(departmentId).then((loadedCycles) => {
      if (active) setCycles(loadedCycles)
    }).catch(() => {
      if (active) setError('Не удалось загрузить доступные циклы')
    })
    return () => {
      active = false
    }
  }, [departmentId, request])

  useEffect(() => {
    if (!request || request.status !== 'DRAFT') return
    const timer = window.setInterval(() => setClockMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [request])

  const secondsLeft = useMemo(
    () => request
      ? remainingSeconds(request, clockMs, receivedAtMs)
      : 0,
    [clockMs, receivedAtMs, request],
  )
  const duplicatesPresent = request
    ? hasBlockingDuplicates(request.lines)
    : false
  const unrecognizedPresent = request
    ? hasUnrecognizedLines(request.lines)
    : false

  async function handleCheck(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isBusy) return
    const validationError = publicSupplyFormError({
      departmentId,
      cycleId,
      authorName,
      multilineText,
    })
    if (validationError) {
      setError(validationError)
      return
    }
    setIsBusy(true)
    setError('')
    try {
      if (request && publicToken && isEditing) {
        const updated = await updatePublicSupplyLines(publicToken, {
          expected_version: request.version,
          multiline_text: multilineText,
        })
        applyRequest(updated)
      } else {
        const created = await createPublicSupplyRequest({
          department_id: departmentId,
          cycle_id: cycleId,
          author_name: authorName.trim(),
          author_phone: authorPhone.trim() || null,
          multiline_text: multilineText,
        })
        sessionStorage.setItem(
          PUBLIC_SUPPLY_SESSION_KEY,
          created.public_token,
        )
        setPublicToken(created.public_token)
        applyRequest(created)
      }
      setIsEditing(false)
      setConfirmUnrecognized(false)
    } catch (caught) {
      setError(safeMessage(caught))
    } finally {
      setIsBusy(false)
    }
  }

  function startEditing() {
    if (!request || secondsLeft <= 0) return
    setDepartmentId(request.department.id)
    setCycleId(request.cycle.id)
    setAuthorName(request.author_name)
    setMultilineText(requestLinesAsText(request))
    setIsEditing(true)
    setError('')
  }

  async function handleSubmit() {
    if (!request || !publicToken || isBusy || duplicatesPresent) return
    if (unrecognizedPresent && !confirmUnrecognized) {
      setError('Подтвердите отправку строк, которые требуют проверки')
      return
    }
    setIsBusy(true)
    setError('')
    try {
      const submitted = await submitPublicSupplyRequest(publicToken, {
        expected_version: request.version,
        confirm_unrecognized: confirmUnrecognized,
      })
      applyRequest(submitted)
    } catch (caught) {
      setError(safeMessage(caught))
      if (
        caught instanceof PublicSupplyApiError
        && caught.code === 'SUPPLY_PUBLIC_REQUEST_NOT_FOUND'
      ) {
        sessionStorage.removeItem(PUBLIC_SUPPLY_SESSION_KEY)
      }
    } finally {
      setIsBusy(false)
    }
  }

  if (isLoading) {
    return (
      <main className="public-request-page">
        <p className="supply-loading">Загружаем форму…</p>
      </main>
    )
  }

  const showForm = !request || isEditing
  const submitted = request?.status === 'SUBMITTED'

  return (
    <main className="public-request-page">
      <section className="request-page supply-request-page">
        <div className="public-request-brand">
          <span className="brand-mark">EOS</span>
          <div>
            <p className="eyebrow">ENTERPRISEOS</p>
            <strong>Заявки подразделений</strong>
          </div>
        </div>

        <div className="request-panel">
          <div className="request-heading">
            <div>
              <p className="eyebrow">ПУБЛИЧНАЯ SUPPLY-ФОРМА</p>
              <h1>{submitted ? 'Заявка отправлена' : 'Заявка на снабжение'}</h1>
              {!submitted && (
                <p className="request-intro">
                  Введите каждую позицию с новой строки и проверьте результат.
                </p>
              )}
            </div>
          </div>

          {showForm ? (
            <form
              className="request-form"
              noValidate
              onSubmit={(event) => void handleCheck(event)}
            >
              <label className="request-field">
                <span>Подразделение</span>
                <select
                  value={departmentId}
                  disabled={isBusy || isEditing}
                  onChange={(event) => {
                    setDepartmentId(event.target.value)
                    setCycleId('')
                    setCycles([])
                    setError('')
                  }}
                >
                  <option value="">Выберите подразделение</option>
                  {departments.map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="request-field">
                <span>Направление и цикл</span>
                <select
                  value={cycleId}
                  disabled={!departmentId || isBusy || isEditing}
                  onChange={(event) => {
                    setCycleId(event.target.value)
                    setError('')
                  }}
                >
                  <option value="">
                    {departmentId && cycles.length === 0
                      ? 'Нет открытых циклов'
                      : 'Выберите доступный цикл'}
                  </option>
                  {cycles.map((cycle) => (
                    <option key={cycle.id} value={cycle.id}>
                      {cycle.direction.name} · {cycle.cycle_date}
                    </option>
                  ))}
                </select>
              </label>

              <label className="request-field">
                <span>Ваше имя</span>
                <input
                  value={authorName}
                  maxLength={160}
                  disabled={isBusy || isEditing}
                  autoComplete="name"
                  onChange={(event) => setAuthorName(event.target.value)}
                />
              </label>

              <label className="request-field">
                <span>Телефон (необязательно)</span>
                <input
                  value={authorPhone}
                  maxLength={40}
                  disabled={isBusy || isEditing}
                  inputMode="tel"
                  autoComplete="tel"
                  onChange={(event) => setAuthorPhone(event.target.value)}
                />
              </label>

              <label className="request-field request-field-wide">
                <span>Позиции заявки</span>
                <textarea
                  value={multilineText}
                  maxLength={PUBLIC_SUPPLY_MAX_TEXT_LENGTH}
                  rows={8}
                  disabled={isBusy}
                  placeholder={EXAMPLES.join('\n')}
                  onChange={(event) => {
                    setMultilineText(event.target.value)
                    setError('')
                  }}
                />
                <small className="supply-examples">
                  Например: {EXAMPLES.join(' · ')}
                </small>
              </label>

              {error && (
                <p className="request-message request-message-error">{error}</p>
              )}

              <button
                className="primary-action request-submit"
                type="submit"
                disabled={isBusy || (!isEditing && cycles.length === 0)}
              >
                {isBusy ? 'Проверяем…' : 'Проверить заявку'}
              </button>
            </form>
          ) : request && (
            <div className="supply-review">
              <div className="supply-summary">
                <strong>{request.request_number}</strong>
                <span>{request.department.name}</span>
                <span>{request.direction.name}</span>
                <span>
                  {new Date(request.cycle.cycle_date).toLocaleDateString('ru-RU')}
                </span>
              </div>

              {!submitted && (
                <div className={`supply-deadline ${secondsLeft === 0 ? 'is-closed' : ''}`}>
                  <span>До закрытия</span>
                  <strong>{formatRemainingTime(secondsLeft)}</strong>
                </div>
              )}

              <ul className="supply-lines">
                {request.lines.map((line) => {
                  const duplicate = line.duplicate_status === 'SUSPECTED'
                    || line.duplicate_status === 'CONFIRMED'
                  const matched = line.match_status === 'MATCHED'
                  return (
                    <li
                      key={line.id}
                      className={duplicate
                        ? 'is-duplicate'
                        : matched ? 'is-matched' : 'needs-review'}
                    >
                      <div>
                        <strong>{line.raw_text}</strong>
                        <span>
                          {line.matched_product_name || line.parsed_name || 'Не распознано'}
                          {' · '}
                          {line.requested_quantity || line.parsed_quantity || '—'}
                          {' '}
                          {line.requested_unit || line.parsed_unit || ''}
                        </span>
                      </div>
                      <em>{line.public_message}</em>
                    </li>
                  )
                })}
              </ul>

              {duplicatesPresent && !submitted && (
                <p className="supply-warning">
                  Есть возможные дубли. Нажмите «Изменить» и оставьте каждую
                  позицию один раз.
                </p>
              )}

              {unrecognizedPresent && !submitted && !duplicatesPresent && (
                <label className="supply-confirm">
                  <input
                    type="checkbox"
                    checked={confirmUnrecognized}
                    onChange={(event) =>
                      setConfirmUnrecognized(event.target.checked)
                    }
                  />
                  <span>
                    Отправить заявку вместе со строками, которые требуют проверки
                  </span>
                </label>
              )}

              {submitted ? (
                <p className="request-message request-message-success">
                  Заявка принята. Изменения после отправки недоступны.
                </p>
              ) : (
                <div className="supply-actions">
                  <button
                    className="secondary-action"
                    type="button"
                    disabled={isBusy || secondsLeft === 0}
                    onClick={startEditing}
                  >
                    Изменить
                  </button>
                  <button
                    className="primary-action"
                    type="button"
                    disabled={
                      isBusy
                      || duplicatesPresent
                      || secondsLeft === 0
                      || (unrecognizedPresent && !confirmUnrecognized)
                    }
                    onClick={() => void handleSubmit()}
                  >
                    {isBusy ? 'Отправляем…' : 'Отправить заявку'}
                  </button>
                </div>
              )}

              {error && (
                <p className="request-message request-message-error">{error}</p>
              )}
            </div>
          )}
        </div>
      </section>
    </main>
  )
}

export default PublicSupplyRequestPage
