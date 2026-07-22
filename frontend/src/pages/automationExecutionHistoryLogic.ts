import type {
  AutomationExecution,
  AutomationExecutionHistoryItem,
  AutomationExecutionHistoryPage,
} from '../services/automation'

export type HistoryApi = (
  scheduleId: number,
  limit: number,
  offset: number,
) => Promise<AutomationExecutionHistoryPage>

export type HistoryLoadResult =
  | { status: 'success'; page: AutomationExecutionHistoryPage }
  | { status: 'error'; message: string }

export function getHistoryErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : ''

  if (/automation schedule not found/i.test(message)) {
    return 'Регламент не найден. Обновите список'
  }

  if (/сессия не найдена/i.test(message)) {
    return 'Сессия завершена. Войдите снова'
  }

  return 'Не удалось загрузить историю запусков. Попробуйте ещё раз'
}

export async function loadExecutionHistory(
  scheduleId: number,
  pageNumber: number,
  pageSize: number,
  api: HistoryApi,
): Promise<HistoryLoadResult> {
  try {
    return {
      status: 'success',
      page: await api(
        scheduleId,
        pageSize,
        (pageNumber - 1) * pageSize,
      ),
    }
  } catch (error) {
    return {
      status: 'error',
      message: getHistoryErrorMessage(error),
    }
  }
}

export function manualExecutionHistoryItem(
  execution: AutomationExecution,
): AutomationExecutionHistoryItem {
  return {
    status: execution.status,
    requested_at: execution.requested_at,
    started_at: execution.started_at,
    finished_at: execution.finished_at,
    duration_seconds: null,
    error_code: null,
    error_message: null,
  }
}

export function prependManualExecution(
  page: AutomationExecutionHistoryPage,
  execution: AutomationExecution,
): AutomationExecutionHistoryPage {
  if (page.offset !== 0) {
    return page
  }

  const newItem = manualExecutionHistoryItem(execution)

  return {
    ...page,
    items: [newItem, ...page.items].slice(0, page.limit),
    total: page.total + 1,
  }
}

export async function updateHistoryAfterManualExecution(
  page: AutomationExecutionHistoryPage,
  execution: AutomationExecution,
  scheduleId: number,
  pageSize: number,
  api: HistoryApi,
): Promise<HistoryLoadResult> {
  if (page.offset === 0) {
    return {
      status: 'success',
      page: prependManualExecution(page, execution),
    }
  }

  return loadExecutionHistory(scheduleId, 1, pageSize, api)
}

export function canReuseHistory(
  loadedScheduleId: number | null,
  scheduleId: number,
  page: AutomationExecutionHistoryPage | null,
): page is AutomationExecutionHistoryPage {
  return loadedScheduleId === scheduleId && page !== null
}
