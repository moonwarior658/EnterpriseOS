import type {
  AutomationExecution,
  AutomationLatestExecution,
} from '../services/automation'
import { latestExecutionFromManualRun } from './automationLatestExecutionsLogic.ts'

export type ManualRunApi = (
  scheduleId: number,
) => Promise<AutomationExecution>

export type ManualRunGuard = {
  runningIds: Set<number>
}

export type ManualRunResult =
  | { status: 'success'; execution: AutomationExecution }
  | { status: 'busy' }
  | { status: 'error'; message: string }

export function createManualRunGuard(): ManualRunGuard {
  return { runningIds: new Set() }
}

export function getManualRunErrorMessage(error: unknown): string {
  const message = error instanceof Error ? error.message : ''

  if (/disabled automation schedule/i.test(message)) {
    return 'Сначала включите регламент'
  }

  if (/automation schedule not found/i.test(message)) {
    return 'Регламент не найден. Обновите список'
  }

  if (/сессия не найдена/i.test(message)) {
    return 'Сессия завершена. Войдите снова'
  }

  return 'Не удалось запустить регламент. Попробуйте ещё раз'
}

export async function runScheduleNow(
  scheduleId: number,
  api: ManualRunApi,
  guard: ManualRunGuard,
): Promise<ManualRunResult> {
  if (guard.runningIds.has(scheduleId)) {
    return { status: 'busy' }
  }

  guard.runningIds.add(scheduleId)

  try {
    return {
      status: 'success',
      execution: await api(scheduleId),
    }
  } catch (error) {
    return {
      status: 'error',
      message: getManualRunErrorMessage(error),
    }
  } finally {
    guard.runningIds.delete(scheduleId)
  }
}

export function updateLatestExecution(
  current: Map<number, AutomationLatestExecution>,
  scheduleId: number,
  execution: AutomationExecution,
): Map<number, AutomationLatestExecution> {
  const next = new Map(current)
  next.set(scheduleId, latestExecutionFromManualRun(scheduleId, execution))
  return next
}
