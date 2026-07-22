import { useEffect, useMemo, useRef, useState } from 'react'
import {
  getAutomationSchedules,
  getLatestScheduleExecution,
  getScheduleExecutionHistory,
  runAutomationSchedule,
  updateAutomationScheduleEnabled,
  type AutomationExecution,
  type AutomationExecutionHistoryPage,
  type AutomationExecutionStatus,
  type AutomationSchedule,
  type AutomationScopeType,
  type ScheduleConfig,
} from '../services/automation'
import AutomationScheduleForm from './AutomationScheduleForm'
import {
  createManualRunGuard,
  runScheduleNow,
  updateLatestExecution,
} from './automationScheduleRunLogic'
import {
  canReuseHistory,
  loadExecutionHistory,
  updateHistoryAfterManualExecution,
} from './automationExecutionHistoryLogic'
import './AutomationSchedulesPage.css'

const PAGE_SIZE = 8
const HISTORY_PAGE_SIZE = 6
const WEEKDAY_LABELS = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс']

type StateFilter =
  | 'all'
  | 'active'
  | 'inactive'
  | 'errors'
  | 'successful'

function formatDate(value: string | null): string {
  if (!value) {
    return '—'
  }

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) {
    return '—'
  }

  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function formatDuration(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value < 0) {
    return '—'
  }

  const totalSeconds = Math.round(value)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60

  return minutes > 0 ? `${minutes} мин ${seconds} сек` : `${seconds} сек`
}

function formatSchedule(config: ScheduleConfig): string {
  if (config.type === 'daily') {
    return `Ежедневно, ${config.time}`
  }

  if (config.type === 'weekly') {
    const weekdays = config.weekdays
      .map((weekday) => WEEKDAY_LABELS[weekday])
      .filter((weekday): weekday is string => Boolean(weekday))
      .join(', ')

    return `Еженедельно: ${weekdays || '—'}, ${config.time}`
  }

  return `Каждые ${config.minutes} мин.`
}

function formatScope(
  scopeType: AutomationScopeType,
  scopeId: string | null,
): string {
  const labels: Record<AutomationScopeType, string> = {
    company: 'Вся компания',
    department: 'Подразделение',
    location: 'Объект',
    user: 'Пользователь',
  }

  return scopeId ? `${labels[scopeType]} · ${scopeId}` : labels[scopeType]
}

function getScopeKey(schedule: AutomationSchedule): string {
  return `${schedule.scope_type}:${schedule.scope_id ?? ''}`
}

function getStatusLabel(status: AutomationExecutionStatus): string {
  const labels: Record<AutomationExecutionStatus, string> = {
    pending: 'Ожидает',
    dispatching: 'Отправляется',
    running: 'Выполняется',
    retrying: 'Повтор',
    succeeded: 'Успешно',
    failed: 'Ошибка',
    timed_out: 'Тайм-аут',
    cancelled: 'Отменён',
  }

  return labels[status]
}

function getStatusClass(status: AutomationExecutionStatus): string {
  if (status === 'succeeded') {
    return 'execution-badge execution-badge-success'
  }

  if (status === 'failed' || status === 'timed_out') {
    return 'execution-badge execution-badge-error'
  }

  if (status === 'retrying') {
    return 'execution-badge execution-badge-warning'
  }

  return 'execution-badge'
}

function AutomationSchedulesPage() {
  const [schedules, setSchedules] = useState<AutomationSchedule[]>([])
  const [latestExecutions, setLatestExecutions] = useState<
    Map<number, AutomationExecution | null>
  >(new Map())
  const [isLoading, setIsLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [error, setError] = useState('')
  const [updatingIds, setUpdatingIds] = useState<Set<number>>(new Set())
  const [runningIds, setRunningIds] = useState<Set<number>>(new Set())
  const manualRunGuard = useRef(createManualRunGuard())
  const [search, setSearch] = useState('')
  const [stateFilter, setStateFilter] = useState<StateFilter>('all')
  const [scopeFilter, setScopeFilter] = useState('all')
  const [typeFilter, setTypeFilter] = useState('all')
  const [currentPage, setCurrentPage] = useState(1)
  const [formSchedule, setFormSchedule] =
    useState<AutomationSchedule | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [notice, setNotice] = useState('')
  const [historyScheduleId, setHistoryScheduleId] = useState<number | null>(
    null,
  )
  const [loadedHistoryScheduleId, setLoadedHistoryScheduleId] = useState<
    number | null
  >(null)
  const [historyPageNumber, setHistoryPageNumber] = useState(1)
  const [historyPage, setHistoryPage] =
    useState<AutomationExecutionHistoryPage | null>(null)
  const [isHistoryLoading, setIsHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState('')
  const historyRequestId = useRef(0)

  useEffect(() => {
    let isMounted = true

    async function loadSchedules() {
      try {
        const loadedSchedules = await getAutomationSchedules()
        const executionResults = await Promise.allSettled(
          loadedSchedules.map((schedule) =>
            getLatestScheduleExecution(schedule.id),
          ),
        )

        if (!isMounted) {
          return
        }

        const loadedExecutions = new Map<
          number,
          AutomationExecution | null
        >()
        let failedExecutionRequests = 0

        executionResults.forEach((result, index) => {
          const schedule = loadedSchedules[index]

          if (!schedule) {
            return
          }

          if (result.status === 'fulfilled') {
            loadedExecutions.set(schedule.id, result.value)
          } else {
            loadedExecutions.set(schedule.id, null)
            failedExecutionRequests += 1
          }
        })

        setSchedules(loadedSchedules)
        setLatestExecutions(loadedExecutions)

        if (failedExecutionRequests > 0) {
          setError(
            `Не удалось загрузить последние статусы для ${failedExecutionRequests} задач`,
          )
        }
      } catch (requestError) {
        if (!isMounted) {
          return
        }

        setLoadFailed(true)
        setError(
          requestError instanceof Error
            ? requestError.message
            : 'Не удалось загрузить регламентные задачи',
        )
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    void loadSchedules()

    return () => {
      isMounted = false
    }
  }, [])

  const scopeOptions = useMemo(() => {
    const options = new Map<string, string>()

    schedules.forEach((schedule) => {
      options.set(
        getScopeKey(schedule),
        formatScope(schedule.scope_type, schedule.scope_id),
      )
    })

    return [...options.entries()].sort((left, right) =>
      left[1].localeCompare(right[1], 'ru'),
    )
  }, [schedules])

  const typeOptions = useMemo(
    () =>
      [...new Set(schedules.map((schedule) => schedule.automation_type))]
        .sort((left, right) => left.localeCompare(right, 'ru')),
    [schedules],
  )

  const filteredSchedules = useMemo(() => {
    const normalizedSearch = search.trim().toLocaleLowerCase('ru')

    return schedules.filter((schedule) => {
      const latestExecution = latestExecutions.get(schedule.id)
      const matchesSearch = schedule.name
        .toLocaleLowerCase('ru')
        .includes(normalizedSearch)
      const matchesScope =
        scopeFilter === 'all' || getScopeKey(schedule) === scopeFilter
      const matchesType =
        typeFilter === 'all' || schedule.automation_type === typeFilter

      let matchesState = true

      if (stateFilter === 'active') {
        matchesState = schedule.is_enabled
      } else if (stateFilter === 'inactive') {
        matchesState = !schedule.is_enabled
      } else if (stateFilter === 'errors') {
        matchesState =
          latestExecution?.status === 'failed' ||
          latestExecution?.status === 'timed_out'
      } else if (stateFilter === 'successful') {
        matchesState = latestExecution?.status === 'succeeded'
      }

      return matchesSearch && matchesScope && matchesType && matchesState
    })
  }, [
    latestExecutions,
    schedules,
    scopeFilter,
    search,
    stateFilter,
    typeFilter,
  ])

  const totalPages = Math.max(
    1,
    Math.ceil(filteredSchedules.length / PAGE_SIZE),
  )
  const displayedPage = Math.min(currentPage, totalPages)
  const pageSchedules = filteredSchedules.slice(
    (displayedPage - 1) * PAGE_SIZE,
    displayedPage * PAGE_SIZE,
  )

  function resetPage() {
    setCurrentPage(1)
  }

  function openCreateForm() {
    setFormSchedule(null)
    setIsFormOpen(true)
    setError('')
    setNotice('')
  }

  function openEditForm(schedule: AutomationSchedule) {
    setFormSchedule(schedule)
    setIsFormOpen(true)
    setError('')
    setNotice('')
  }

  function closeForm() {
    setIsFormOpen(false)
    setFormSchedule(null)
  }

  function handleScheduleSaved(
    savedSchedule: AutomationSchedule,
    isCreated: boolean,
  ) {
    setSchedules((current) =>
      isCreated
        ? [...current, savedSchedule]
        : current.map((item) =>
            item.id === savedSchedule.id ? savedSchedule : item,
          ),
    )

    if (isCreated) {
      setLatestExecutions((current) => {
        const next = new Map(current)
        next.set(savedSchedule.id, null)
        return next
      })
    }

    setNotice(
      isCreated
        ? 'Регламент создан'
        : 'Изменения регламента сохранены',
    )
    closeForm()
    resetPage()
  }

  async function handleToggle(schedule: AutomationSchedule) {
    setError('')
    setUpdatingIds((current) => new Set(current).add(schedule.id))

    try {
      const updatedSchedule = await updateAutomationScheduleEnabled(
        schedule.id,
        !schedule.is_enabled,
      )

      setSchedules((current) =>
        current.map((item) =>
          item.id === schedule.id
            ? updatedSchedule ?? {
                ...item,
                is_enabled: !item.is_enabled,
              }
            : item,
        ),
      )
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : 'Не удалось изменить состояние задачи',
      )
    } finally {
      setUpdatingIds((current) => {
        const next = new Set(current)
        next.delete(schedule.id)
        return next
      })
    }
  }

  async function handleManualRun(schedule: AutomationSchedule) {
    if (manualRunGuard.current.runningIds.has(schedule.id)) {
      return
    }

    setError('')
    setNotice('')
    setRunningIds((current) => new Set(current).add(schedule.id))

    const result = await runScheduleNow(
      schedule.id,
      runAutomationSchedule,
      manualRunGuard.current,
    )

    if (result.status === 'success') {
      setLatestExecutions((current) =>
        updateLatestExecution(current, schedule.id, result.execution),
      )
      setNotice(`Регламент «${schedule.name}» поставлен в очередь`)
      if (historyScheduleId === schedule.id) {
        if (historyPage) {
          const shouldReloadFirstPage = historyPage.offset > 0
          const requestId = historyRequestId.current + 1
          historyRequestId.current = requestId
          setHistoryPageNumber(1)
          setHistoryError('')
          setIsHistoryLoading(shouldReloadFirstPage)

          const historyResult = await updateHistoryAfterManualExecution(
            historyPage,
            result.execution,
            schedule.id,
            HISTORY_PAGE_SIZE,
            getScheduleExecutionHistory,
          )

          if (historyRequestId.current === requestId) {
            if (historyResult.status === 'success') {
              setHistoryPage(historyResult.page)
              setLoadedHistoryScheduleId(schedule.id)
            } else {
              setHistoryPage(null)
              setHistoryError(historyResult.message)
            }
            setIsHistoryLoading(false)
          }
        } else {
          setHistoryPage({
            items: [
              {
                status: result.execution.status,
                requested_at: result.execution.requested_at,
                started_at: result.execution.started_at,
                finished_at: result.execution.finished_at,
                duration_seconds: null,
                error_code: null,
                error_message: null,
              },
            ],
            total: 1,
            limit: HISTORY_PAGE_SIZE,
            offset: 0,
          })
          setHistoryPageNumber(1)
        }
      }
    } else if (result.status === 'error') {
      setError(result.message)
    }

    setRunningIds((current) => {
      const next = new Set(current)
      next.delete(schedule.id)
      return next
    })
  }

  async function loadHistory(scheduleId: number, pageNumber: number) {
    const requestId = historyRequestId.current + 1
    historyRequestId.current = requestId
    setHistoryScheduleId(scheduleId)
    setHistoryPageNumber(pageNumber)
    setIsHistoryLoading(true)
    setHistoryError('')

    const result = await loadExecutionHistory(
      scheduleId,
      pageNumber,
      HISTORY_PAGE_SIZE,
      getScheduleExecutionHistory,
    )

    if (historyRequestId.current !== requestId) {
      return
    }

    if (result.status === 'success') {
      setHistoryPage(result.page)
      setLoadedHistoryScheduleId(scheduleId)
    } else {
      setHistoryPage(null)
      setHistoryError(result.message)
    }
    setIsHistoryLoading(false)
  }

  function handleHistoryToggle(scheduleId: number) {
    if (historyScheduleId === scheduleId) {
      setHistoryScheduleId(null)
      return
    }

    if (
      canReuseHistory(loadedHistoryScheduleId, scheduleId, historyPage)
    ) {
      setHistoryScheduleId(scheduleId)
      return
    }

    void loadHistory(scheduleId, 1)
  }

  const historySchedule = schedules.find(
    (schedule) => schedule.id === historyScheduleId,
  )
  const historyTotalPages = Math.max(
    1,
    Math.ceil((historyPage?.total ?? 0) / HISTORY_PAGE_SIZE),
  )

  return (
    <main className="app-page automation-page">
      <div className="page-shell automation-page-shell">
        <section className="page-panel automation-panel">
          <div className="page-title-row automation-title-row">
            <div>
              <p className="eyebrow">АВТОМАТИЗАЦИЯ</p>
              <h1>Регламентные задачи</h1>
              <p className="subtitle">
                Расписания и состояние регулярных процессов
              </p>
            </div>

            <button
              className="primary-action"
              type="button"
              disabled={isFormOpen}
              onClick={openCreateForm}
            >
              Добавить
            </button>
          </div>

          {isFormOpen && (
            <AutomationScheduleForm
              key={formSchedule?.id ?? 'create'}
              schedule={formSchedule}
              automationTypes={typeOptions}
              onCancel={closeForm}
              onSaved={handleScheduleSaved}
            />
          )}

          <div className="automation-filters" aria-label="Фильтры задач">
            <label className="automation-search">
              <span>Поиск</span>
              <input
                type="search"
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value)
                  resetPage()
                }}
                placeholder="По названию"
              />
            </label>

            <label>
              <span>Состояние</span>
              <select
                value={stateFilter}
                onChange={(event) => {
                  setStateFilter(event.target.value as StateFilter)
                  resetPage()
                }}
              >
                <option value="all">Все</option>
                <option value="active">Активные</option>
                <option value="inactive">Выключенные</option>
                <option value="errors">С ошибками</option>
                <option value="successful">Успешные</option>
              </select>
            </label>

            <label>
              <span>Подразделение / scope</span>
              <select
                value={scopeFilter}
                onChange={(event) => {
                  setScopeFilter(event.target.value)
                  resetPage()
                }}
              >
                <option value="all">Все</option>
                {scopeOptions.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              <span>Тип автоматизации</span>
              <select
                value={typeFilter}
                onChange={(event) => {
                  setTypeFilter(event.target.value)
                  resetPage()
                }}
              >
                <option value="all">Все</option>
                {typeOptions.map((automationType) => (
                  <option key={automationType} value={automationType}>
                    {automationType}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {error && <p className="page-error">{error}</p>}
          {notice && (
            <p className="automation-page-notice" role="status">
              {notice}
            </p>
          )}

          {!loadFailed && (
            <div className="automation-table-wrap">
              <table className="automation-table">
                <colgroup>
                  <col className="automation-column-name" />
                  <col className="automation-column-type" />
                  <col className="automation-column-scope" />
                  <col className="automation-column-schedule" />
                  <col className="automation-column-next-run" />
                  <col className="automation-column-status" />
                  <col className="automation-column-enabled" />
                  <col className="automation-column-actions" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Название</th>
                    <th>Тип</th>
                    <th>Подразделение</th>
                    <th>Расписание</th>
                    <th>Следующий запуск</th>
                    <th>Последний статус</th>
                    <th>Активен</th>
                    <th aria-label="Действия" />
                  </tr>
                </thead>
                <tbody>
                  {isLoading && (
                    <tr>
                      <td className="automation-table-state" colSpan={8}>
                        Загружаем регламентные задачи…
                      </td>
                    </tr>
                  )}

                  {!isLoading && schedules.length === 0 && (
                    <tr>
                      <td className="automation-table-state" colSpan={8}>
                        Регламентные задачи пока не созданы
                      </td>
                    </tr>
                  )}

                  {!isLoading &&
                    schedules.length > 0 &&
                    filteredSchedules.length === 0 && (
                      <tr>
                        <td className="automation-table-state" colSpan={8}>
                          По выбранным фильтрам задач нет
                        </td>
                      </tr>
                    )}

                  {!isLoading &&
                    pageSchedules.map((schedule) => {
                      const latestExecution = latestExecutions.get(schedule.id)
                      const isUpdating = updatingIds.has(schedule.id)
                      const isRunning = runningIds.has(schedule.id)

                      return (
                        <tr key={schedule.id}>
                          <td>
                            <div className="automation-name-cell">
                              <strong title={schedule.name}>
                                {schedule.name}
                              </strong>
                              <span>ID {schedule.id}</span>
                            </div>
                          </td>
                          <td>
                            <span
                              className="automation-type-badge"
                              title={schedule.automation_type}
                            >
                              {schedule.automation_type}
                            </span>
                          </td>
                          <td>
                            <span
                              className="automation-truncated"
                              title={formatScope(
                                schedule.scope_type,
                                schedule.scope_id,
                              )}
                            >
                              {formatScope(
                                schedule.scope_type,
                                schedule.scope_id,
                              )}
                            </span>
                          </td>
                          <td>
                            <span
                              className="automation-truncated"
                              title={`${formatSchedule(schedule.schedule_config)} · ${schedule.timezone}`}
                            >
                              {formatSchedule(schedule.schedule_config)}
                            </span>
                          </td>
                          <td className="automation-date-cell">
                            {formatDate(schedule.next_run_at)}
                          </td>
                          <td>
                            <div className="execution-status-cell">
                              {latestExecution ? (
                                <span
                                  className={getStatusClass(
                                    latestExecution.status,
                                  )}
                                >
                                  {getStatusLabel(latestExecution.status)}
                                </span>
                              ) : (
                                <span className="execution-badge">
                                  Нет запусков
                                </span>
                              )}
                              <span>
                                {formatDate(
                                  latestExecution?.requested_at ?? null,
                                )}
                              </span>
                            </div>
                          </td>
                          <td>
                            <button
                              className="schedule-toggle"
                              type="button"
                              role="switch"
                              aria-checked={schedule.is_enabled}
                              aria-label={`${schedule.is_enabled ? 'Выключить' : 'Включить'} задачу ${schedule.name}`}
                              disabled={isUpdating}
                              title={
                                schedule.is_enabled
                                  ? 'Выключить задачу'
                                  : 'Включить задачу'
                              }
                              onClick={() => void handleToggle(schedule)}
                            >
                              <span />
                            </button>
                          </td>
                          <td>
                            <div className="automation-row-action-list">
                              <button
                                className="automation-row-actions automation-run-action"
                                type="button"
                                disabled={
                                  !schedule.is_enabled ||
                                  isRunning ||
                                  isFormOpen
                                }
                                title={
                                  schedule.is_enabled
                                    ? 'Запустить регламент сейчас'
                                    : 'Сначала включите регламент'
                                }
                                aria-label={`Запустить сейчас задачу ${schedule.name}`}
                                onClick={() => void handleManualRun(schedule)}
                              >
                                {isRunning ? 'Запускаем…' : 'Запустить'}
                              </button>
                              <button
                                className="automation-row-actions"
                                type="button"
                                disabled={isFormOpen || isRunning}
                                aria-expanded={
                                  historyScheduleId === schedule.id
                                }
                                aria-controls="automation-execution-history"
                                title="Открыть историю запусков"
                                onClick={() =>
                                  handleHistoryToggle(schedule.id)
                                }
                              >
                                История
                              </button>
                              <button
                                className="automation-row-actions"
                                type="button"
                                disabled={isFormOpen || isRunning}
                                title="Редактировать регламент"
                                aria-label={`Редактировать задачу ${schedule.name}`}
                                onClick={() => openEditForm(schedule)}
                              >
                                Изменить
                              </button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                </tbody>
              </table>
            </div>
          )}

          {!isLoading && !loadFailed && (
            <div className="automation-pagination">
              <span>
                Показано {pageSchedules.length} из {filteredSchedules.length}{' '}
                задач
              </span>

              <nav aria-label="Пагинация регламентных задач">
                <button
                  type="button"
                  disabled={displayedPage === 1}
                  onClick={() => setCurrentPage(displayedPage - 1)}
                  aria-label="Предыдущая страница"
                >
                  ←
                </button>

                {Array.from({ length: totalPages }, (_, index) => {
                  const page = index + 1

                  return (
                    <button
                      className={
                        page === displayedPage
                          ? 'pagination-page-active'
                          : undefined
                      }
                      type="button"
                      key={page}
                      onClick={() => setCurrentPage(page)}
                      aria-current={
                        page === displayedPage ? 'page' : undefined
                      }
                    >
                      {page}
                    </button>
                  )
                })}

                <button
                  type="button"
                  disabled={displayedPage === totalPages}
                  onClick={() => setCurrentPage(displayedPage + 1)}
                  aria-label="Следующая страница"
                >
                  →
                </button>
              </nav>
            </div>
          )}

          {historySchedule && (
            <section
              className="automation-history"
              id="automation-execution-history"
              aria-labelledby="automation-history-title"
            >
              <div className="automation-history-heading">
                <div>
                  <p className="eyebrow">ИСТОРИЯ ЗАПУСКОВ</p>
                  <h2 id="automation-history-title">
                    {historySchedule.name}
                  </h2>
                </div>
                <button
                  className="automation-history-close"
                  type="button"
                  aria-label="Закрыть историю запусков"
                  onClick={() => setHistoryScheduleId(null)}
                >
                  ×
                </button>
              </div>

              {isHistoryLoading && (
                <p className="automation-history-state" role="status">
                  Загружаем историю запусков…
                </p>
              )}

              {!isHistoryLoading && historyError && (
                <div className="automation-history-error" role="alert">
                  <span>{historyError}</span>
                  <button
                    type="button"
                    onClick={() =>
                      void loadHistory(
                        historySchedule.id,
                        historyPageNumber,
                      )
                    }
                  >
                    Повторить
                  </button>
                </div>
              )}

              {!isHistoryLoading &&
                !historyError &&
                historyPage?.items.length === 0 && (
                  <p className="automation-history-state">
                    У этого регламента пока нет запусков
                  </p>
                )}

              {!isHistoryLoading &&
                !historyError &&
                historyPage &&
                historyPage.items.length > 0 && (
                  <div className="automation-history-table-wrap">
                    <table className="automation-history-table">
                      <thead>
                        <tr>
                          <th>Статус</th>
                          <th>Запрошен</th>
                          <th>Старт</th>
                          <th>Завершён</th>
                          <th>Длительность</th>
                          <th>Причина ошибки</th>
                        </tr>
                      </thead>
                      <tbody>
                        {historyPage.items.map((execution, index) => (
                          <tr
                            key={`${execution.requested_at}-${index}`}
                          >
                            <td>
                              <span
                                className={getStatusClass(execution.status)}
                              >
                                {getStatusLabel(execution.status)}
                              </span>
                            </td>
                            <td>{formatDate(execution.requested_at)}</td>
                            <td>{formatDate(execution.started_at)}</td>
                            <td>{formatDate(execution.finished_at)}</td>
                            <td>
                              {formatDuration(execution.duration_seconds)}
                            </td>
                            <td className="automation-history-error-cell">
                              {execution.error_message ?? '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}

              {!isHistoryLoading &&
                !historyError &&
                historyPage &&
                historyPage.total > 0 && (
                  <div className="automation-history-pagination">
                    <span>
                      Страница {historyPageNumber} из {historyTotalPages} ·{' '}
                      запусков: {historyPage.total}
                    </span>
                    <nav aria-label="Пагинация истории запусков">
                      <button
                        type="button"
                        disabled={historyPageNumber === 1}
                        onClick={() =>
                          void loadHistory(
                            historySchedule.id,
                            historyPageNumber - 1,
                          )
                        }
                      >
                        ← Назад
                      </button>
                      <button
                        type="button"
                        disabled={historyPageNumber >= historyTotalPages}
                        onClick={() =>
                          void loadHistory(
                            historySchedule.id,
                            historyPageNumber + 1,
                          )
                        }
                      >
                        Вперёд →
                      </button>
                    </nav>
                  </div>
                )}
            </section>
          )}
        </section>
      </div>
    </main>
  )
}

export default AutomationSchedulesPage
