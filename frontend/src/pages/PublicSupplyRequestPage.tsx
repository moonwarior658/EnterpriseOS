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
  getPublicSupplySchedule,
  PublicSupplyApiError,
  selectPublicSupplyClarification,
  submitPublicSupplyRequest,
  updatePublicSupplyLines,
  type PublicSupplyCycle,
  type PublicSupplyDepartment,
  type PublicSupplyRequest,
  type PublicSupplySchedule,
} from '../services/publicSupply'
import {
  BusinessActionError,
  confirmShiftSubstitution,
  createEmployeeSupplyRequest,
  getActionContext,
  type ActionContext,
  type CreatedEmployeeSupplyRequest,
} from '../services/actionContext'
import { useAuth } from '../contexts/AuthContext'
import {
  EosCheckbox,
  EosDateField,
  EosSelect,
} from '../components/EosFormControls'
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
  if (error instanceof BusinessActionError) return error.message
  return 'Не удалось выполнить запрос. Попробуйте ещё раз'
}

function PublicSupplyRequestPage() {
  const { user } = useAuth()
  const [departments, setDepartments] = useState<PublicSupplyDepartment[]>([])
  const [cycles, setCycles] = useState<PublicSupplyCycle[]>([])
  const [schedule, setSchedule] = useState<PublicSupplySchedule[]>([])
  const [departmentId, setDepartmentId] = useState('')
  const [authorName, setAuthorName] = useState('')
  const [needDate, setNeedDate] = useState('')
  const [multilineText, setMultilineText] = useState('')
  const [request, setRequest] = useState<PublicSupplyRequest | null>(null)
  const [publicToken, setPublicToken] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const [confirmUnrecognized, setConfirmUnrecognized] = useState(false)
  const [isBusy, setIsBusy] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [isCyclesLoading, setIsCyclesLoading] = useState(false)
  const [error, setError] = useState('')
  const [receivedAtMs, setReceivedAtMs] = useState(0)
  const [clockMs, setClockMs] = useState(0)
  const [actionContext, setActionContext] = useState<ActionContext | null>(null)
  const [contextUnavailableUserId, setContextUnavailableUserId] = useState<number | null>(null)
  const [createdInternal, setCreatedInternal] = useState<CreatedEmployeeSupplyRequest | null>(null)
  const [substitution, setSubstitution] = useState<BusinessActionError | null>(null)

  const sellerMode = actionContext?.roles.includes('SELLER') === true
  const contextPending = Boolean(
    user
    && actionContext?.user_id !== user.id
    && contextUnavailableUserId !== user.id,
  )
  const actualDepartmentName = departments.find(
    (department) => department.id === actionContext?.actual_department_id,
  )?.name

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
      getPublicSupplySchedule(),
      storedToken ? getPublicSupplyRequest(storedToken) : Promise.resolve(null),
    ]).then(([departmentsResult, scheduleResult, requestResult]) => {
      if (!active) return
      if (departmentsResult.status === 'fulfilled') {
        setDepartments(departmentsResult.value)
      } else {
        setError('Не удалось загрузить форму. Обновите страницу')
      }
      if (scheduleResult.status === 'fulfilled') {
        setSchedule(scheduleResult.value)
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
          setPublicToken(storedToken)
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
    if (!user) {
      return
    }
    let active = true
    getActionContext()
      .then((context) => {
        if (!active) return
        setContextUnavailableUserId(null)
        setActionContext(context)
        if (context.roles.includes('SELLER')) {
          setDepartmentId(
            context.actual_department_id ?? context.primary_department_id ?? '',
          )
        }
      })
      .catch(() => {
        // Accounts outside the migrated Employee flow keep the public form.
        if (active) setContextUnavailableUserId(user.id)
      })
    return () => { active = false }
  }, [user])

  useEffect(() => {
    if (!departmentId || request) return
    let active = true
    getPublicSupplyCycles(departmentId).then((loadedCycles) => {
      if (active) {
        setCycles(loadedCycles)
      }
    }).catch(() => {
      if (active) setError('Не удалось загрузить доступные циклы')
    }).finally(() => {
      if (active) setIsCyclesLoading(false)
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

  async function retryRestore() {
    if (!publicToken || isBusy) return
    setIsBusy(true)
    setError('')
    try {
      applyRequest(await getPublicSupplyRequest(publicToken))
    } catch (caught) {
      if (
        caught instanceof PublicSupplyApiError
        && caught.code === 'SUPPLY_PUBLIC_REQUEST_NOT_FOUND'
      ) {
        sessionStorage.removeItem(PUBLIC_SUPPLY_SESSION_KEY)
        setPublicToken('')
        setError('Черновик больше недоступен. Создайте новую заявку')
      } else {
        setError('Не удалось восстановить заявку. Попробуйте ещё раз')
      }
    } finally {
      setIsBusy(false)
    }
  }

  async function handleCheck(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isBusy) return
    if (publicToken && !request) {
      setError('Сначала восстановите сохранённую заявку')
      return
    }
    const validationError = publicSupplyFormError({
      departmentId,
      needDate,
      multilineText,
    })
    if (validationError) {
      setError(validationError)
      return
    }
    setIsBusy(true)
    setError('')
    try {
      if (sellerMode && actionContext) {
        const cycle = cycles[0]
        if (!cycle) {
          setError('Сейчас нет доступного цикла приёма заявок')
          return
        }
        const created = await createEmployeeSupplyRequest({
          department_id: departmentId,
          direction_id: cycle.direction.id,
          cycle_id: cycle.id,
          need_date: needDate || null,
          multiline_text: multilineText,
        })
        setCreatedInternal(created)
        return
      }
      if (request && publicToken && isEditing) {
        const updated = await updatePublicSupplyLines(publicToken, {
          expected_version: request.version,
          multiline_text: multilineText,
          need_date: needDate,
        })
        applyRequest(updated)
      } else {
        const created = await createPublicSupplyRequest({
          department_id: departmentId,
          need_date: needDate,
          author_name: authorName.trim() || null,
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
      if (
        caught instanceof BusinessActionError
        && caught.code === 'SHIFT_SUBSTITUTION_CONFIRMATION_REQUIRED'
      ) {
        setSubstitution(caught)
        return
      }
      setError(safeMessage(caught))
    } finally {
      setIsBusy(false)
    }
  }

  async function confirmSubstitutionAndRetry() {
    const shiftId = substitution?.detail.shift_id
    if (!shiftId || isBusy) return
    setIsBusy(true)
    setError('')
    try {
      const context = await confirmShiftSubstitution(shiftId)
      setActionContext(context)
      setSubstitution(null)
      const cycle = cycles[0]
      if (!cycle || !context.actual_department_id) return
      setCreatedInternal(await createEmployeeSupplyRequest({
        department_id: context.actual_department_id,
        direction_id: cycle.direction.id,
        cycle_id: cycle.id,
        need_date: needDate || null,
        multiline_text: multilineText,
      }))
    } catch (caught) {
      setSubstitution(null)
      setError(caught instanceof Error ? caught.message : 'Не удалось подтвердить подмену')
    } finally {
      setIsBusy(false)
    }
  }

  function startEditing() {
    if (!request || secondsLeft <= 0) return
    setDepartmentId(request.department.id)
    setIsCyclesLoading(false)
    setAuthorName(request.author_name ?? '')
    setNeedDate(request.need_date ?? '')
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

  async function handleClarification(lineId: string, productId: string) {
    if (!request || !publicToken || isBusy) return
    setIsBusy(true)
    setError('')
    try {
      applyRequest(await selectPublicSupplyClarification(publicToken, lineId, {
        expected_version: request.version,
        product_id: productId,
      }))
      setConfirmUnrecognized(false)
    } catch (caught) {
      setError(safeMessage(caught))
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


  if (createdInternal) {
    return (
      <main className="public-request-page">
        <section className="request-page supply-request-page">
          <div className="request-panel">
            <p className="eyebrow">ЗАЯВКА СОТРУДНИКА</p>
            <h1>Заявка создана</h1>
            <p className="request-message request-message-success">
              {createdInternal.public_number} · {createdInternal.department.name}
            </p>
            <p>Заявка сохранена как черновик от имени фактического подразделения смены.</p>
          </div>
        </section>
      </main>
    )
  }

  const showForm = !request || isEditing
  const submitted = request?.status === 'SUBMITTED'
  const isInitialState = showForm && !departmentId && !isEditing

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

        <div className={`request-panel${isInitialState ? ' supply-request-initial' : ''}`}>
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

          {sellerMode && actionContext && (
            <div className="supply-shift-status" role="status">
              <strong>Личная смена iiko</strong>
              <span>
                {!actionContext.shift_id
                  ? 'Смена не открыта — создание заявки недоступно'
                  : !actionContext.actual_department_id
                    ? 'Подразделение смены не сопоставлено с EOS'
                    : `Активна с ${new Date(actionContext.shift_opened_at!).toLocaleString('ru-RU')}${actualDepartmentName ? ` · ${actualDepartmentName}` : ''}`}
              </span>
            </div>
          )}
          {contextPending && (
            <div className="supply-shift-status" role="status">
              <strong>Проверяем рабочий контекст…</strong>
              <span>Создание заявки станет доступно после проверки роли и смены.</span>
            </div>
          )}

          {showForm ? (
            <form
              className={`request-form${isInitialState ? ' supply-request-initial-form' : ''}`}
              noValidate
              onSubmit={(event) => void handleCheck(event)}
            >
              <label className="request-field">
                <span>Подразделение</span>
                <EosSelect
                  value={departmentId}
                  disabled={isBusy || isEditing || sellerMode}
                  onChange={(event) => {
                    const nextDepartmentId = event.target.value
                    setDepartmentId(nextDepartmentId)
                    setIsCyclesLoading(Boolean(nextDepartmentId))
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
                </EosSelect>
              </label>

              {departmentId && !isCyclesLoading
                && (cycles.length === 1 || isEditing) && (
              <>
              <label className="request-field">
                <span>Ваше имя (необязательно)</span>
                <input
                  value={authorName}
                  maxLength={160}
                  disabled={isBusy || isEditing}
                  autoComplete="name"
                  onChange={(event) => setAuthorName(event.target.value)}
                />
              </label>

              <EosDateField
                label="Дата потребности"
                value={needDate}
                disabled={isBusy}
                onChange={(event) => {
                  setNeedDate(event.target.value)
                  setError('')
                }}
              />

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
                <>
                  <p className="request-message request-message-error">{error}</p>
                  {!request && publicToken && (
                    <button
                      type="button"
                      disabled={isBusy}
                      onClick={() => void retryRestore()}
                    >
                      Восстановить сохранённую заявку
                    </button>
                  )}
                </>
              )}

              <button
                className="primary-action request-submit"
                type="submit"
                disabled={
                  isBusy
                  || contextPending
                  || (sellerMode && (
                    !actionContext?.shift_id || !actionContext.actual_department_id
                  ))
                }
              >
                {isBusy
                  ? 'Сохраняем…'
                  : sellerMode ? 'Создать заявку' : 'Проверить заявку'}
              </button>
              </>
              )}

              {departmentId && isCyclesLoading && (
                <p className="page-state">Проверяем приём заявок…</p>
              )}

              {departmentId && !isCyclesLoading && !isEditing
                && cycles.length !== 1 && (
                <div className="supply-closed-state">
                  <h2>
                    {cycles.length === 0
                      ? 'Сегодня заявки не принимаем'
                      : 'Сейчас доступно несколько направлений'}
                  </h2>
                  {cycles.length > 1 && (
                    <p>Обратитесь к снабжению, чтобы выбрать нужное направление.</p>
                  )}
                  <div className="supply-public-schedule">
                    {schedule.length > 0 ? (
                      schedule.map((item) => (
                        <p key={item.summary}>{item.summary}</p>
                      ))
                    ) : (
                      <p>Расписание приёма заявок пока не настроено</p>
                    )}
                  </div>
                </div>
              )}
            </form>
          ) : request && (
            <div className="supply-review">
              <div className="supply-summary">
                <strong>{request.request_number}</strong>
                <span>{request.department.name}</span>
                <span>{request.direction.name}</span>
                <span>
                  Дата потребности: {request.need_date
                    ? new Date(`${request.need_date}T00:00:00`).toLocaleDateString('ru-RU')
                    : 'не указана'}
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
                      {line.clarification_options.length > 1 && !submitted && (
                        <div className="supply-clarification">
                          <span>Уточните, какой товар нужен:</span>
                          {line.clarification_options.map((option) => (
                            <button
                              key={option.product_id}
                              type="button"
                              className="secondary-action"
                              disabled={isBusy}
                              onClick={() => void handleClarification(
                                line.id,
                                option.product_id,
                              )}
                            >
                              {option.product_name}
                            </button>
                          ))}
                        </div>
                      )}
                      {['PLANNED', 'PARTIALLY_FULFILLED', 'FULFILLED'].includes(request.status) && (
                        <dl className="public-supply-result">
                          <div><dt>Принято к отправке</dt><dd>{line.confirmed_quantity}</dd></div>
                          <div><dt>Отправлено</dt><dd>{line.fulfilled_quantity}</dd></div>
                          <div><dt>Осталось</dt><dd>{line.unresolved_quantity}</dd></div>
                          <div><dt>Перенесено в долг</dt><dd>{line.debt_quantity}</dd></div>
                        </dl>
                      )}
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
                <EosCheckbox
                    className="supply-confirm"
                    label="Отправить заявку вместе со строками, которые требуют проверки"
                    checked={confirmUnrecognized}
                    onChange={(event) =>
                      setConfirmUnrecognized(event.target.checked)
                    }
                />
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
      {substitution && (
        <div className="employee-dialog-backdrop" role="presentation">
          <section className="employee-dialog" role="dialog" aria-modal="true" aria-labelledby="substitution-title">
            <h2 id="substitution-title">Подтвердите работу на подмене</h2>
            <p>
              Вы работаете в {substitution.detail.actual_department_name ?? 'другом подразделении'},
              {' '}хотя ваше основное подразделение — {substitution.detail.primary_department_name ?? 'другое'}.
              Выполнить действие от имени фактической точки?
            </p>
            <div className="supply-actions">
              <button type="button" className="secondary-action" disabled={isBusy} onClick={() => setSubstitution(null)}>
                Отмена
              </button>
              <button type="button" className="primary-action" disabled={isBusy} onClick={() => void confirmSubstitutionAndRetry()}>
                {isBusy ? 'Подтверждаем…' : 'Подтвердить и продолжить'}
              </button>
            </div>
          </section>
        </div>
      )}
    </main>
  )
}

export default PublicSupplyRequestPage
