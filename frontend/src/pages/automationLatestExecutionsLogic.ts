import type {
  AutomationExecution,
  AutomationExecutionStatus,
  AutomationLatestExecution,
} from '../services/automation'

type UserExecutionPresentation = Pick<
  AutomationLatestExecution,
  'user_status' | 'user_message' | 'error_category' | 'error_code'
>

const USER_EXECUTION_PRESENTATIONS: Record<
  AutomationExecutionStatus,
  UserExecutionPresentation
> = {
  pending: {
    user_status: 'Ожидает запуска',
    user_message: 'Запуск ожидает обработки',
    error_category: null,
    error_code: null,
  },
  dispatching: {
    user_status: 'Запускается',
    user_message: 'Регламент запускается',
    error_category: null,
    error_code: null,
  },
  running: {
    user_status: 'Выполняется',
    user_message: 'Регламент выполняется',
    error_category: null,
    error_code: null,
  },
  retrying: {
    user_status: 'Ожидает повторного запуска',
    user_message: 'Система повторит запуск автоматически',
    error_category: null,
    error_code: null,
  },
  succeeded: {
    user_status: 'Выполнено',
    user_message: 'Регламент выполнен',
    error_category: null,
    error_code: null,
  },
  failed: {
    user_status: 'Ошибка выполнения',
    user_message: 'Не удалось выполнить регламент',
    error_category: 'execution_failed',
    error_code: 'AUTOMATION_FAILED',
  },
  timed_out: {
    user_status: 'Превышено время ожидания',
    user_message: 'Регламент не завершился за отведённое время',
    error_category: 'timeout',
    error_code: 'AUTOMATION_TIMED_OUT',
  },
  cancelled: {
    user_status: 'Отменено',
    user_message: 'Запуск регламента отменён',
    error_category: 'cancelled',
    error_code: 'AUTOMATION_CANCELLED',
  },
}

export type LatestExecutionsApi = (
  scheduleIds: number[],
) => Promise<AutomationLatestExecution[]>

export type LatestExecutionsLoadResult =
  | {
      status: 'success'
      executions: Map<number, AutomationLatestExecution>
    }
  | { status: 'error'; message: string }

export function noLatestExecution(
  scheduleId: number,
): AutomationLatestExecution {
  return {
    schedule_id: scheduleId,
    status: null,
    requested_at: null,
    started_at: null,
    finished_at: null,
    duration_seconds: null,
    user_status: 'Нет запусков',
    user_message: 'Регламент ещё не запускался',
    error_category: null,
    error_code: null,
  }
}

export function getUserExecutionPresentation(
  status: AutomationExecutionStatus,
): UserExecutionPresentation {
  return USER_EXECUTION_PRESENTATIONS[status]
}

export function latestExecutionFromManualRun(
  scheduleId: number,
  execution: AutomationExecution,
): AutomationLatestExecution {
  const presentation = getUserExecutionPresentation(execution.status)

  return {
    schedule_id: scheduleId,
    status: execution.status,
    requested_at: execution.requested_at,
    started_at: execution.started_at,
    finished_at: execution.finished_at,
    duration_seconds: null,
    ...presentation,
  }
}

export async function loadLatestExecutions(
  scheduleIds: number[],
  api: LatestExecutionsApi,
): Promise<LatestExecutionsLoadResult> {
  if (scheduleIds.length === 0) {
    return { status: 'success', executions: new Map() }
  }

  try {
    const items = await api(scheduleIds)
    const executions = new Map(
      items.map((item) => [item.schedule_id, item]),
    )

    scheduleIds.forEach((scheduleId) => {
      if (!executions.has(scheduleId)) {
        executions.set(scheduleId, noLatestExecution(scheduleId))
      }
    })

    return { status: 'success', executions }
  } catch {
    return {
      status: 'error',
      message: 'Не удалось загрузить последние статусы. Попробуйте ещё раз',
    }
  }
}
