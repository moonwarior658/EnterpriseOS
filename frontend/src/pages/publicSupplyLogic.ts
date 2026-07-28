import type {
  PublicSupplyLine,
  PublicSupplyRequest,
} from '../services/publicSupply'

export const PUBLIC_SUPPLY_SESSION_KEY = 'eos_public_supply_token'
export const PUBLIC_SUPPLY_MAX_TEXT_LENGTH = 20_000

export function publicSupplyFormError(values: {
  departmentId: string
  multilineText: string
}): string {
  if (!values.departmentId) return 'Выберите подразделение'
  if (!values.multilineText.trim()) return 'Добавьте хотя бы одну строку заявки'
  if (values.multilineText.length > PUBLIC_SUPPLY_MAX_TEXT_LENGTH) {
    return 'Текст заявки слишком длинный'
  }
  return ''
}

export function hasBlockingDuplicates(lines: PublicSupplyLine[]): boolean {
  return lines.some((line) =>
    line.duplicate_status === 'SUSPECTED'
    || line.duplicate_status === 'CONFIRMED',
  )
}

export function hasUnrecognizedLines(lines: PublicSupplyLine[]): boolean {
  return lines.some((line) => line.match_status !== 'MATCHED')
}

export function remainingSeconds(
  request: PublicSupplyRequest,
  nowMs: number,
  receivedAtMs: number,
): number {
  const serverNowMs = Date.parse(request.cycle.server_now)
  const effectiveCloseMs = Date.parse(request.cycle.effective_closes_at)
  const estimatedServerNow = serverNowMs + (nowMs - receivedAtMs)
  return Math.max(0, Math.ceil((effectiveCloseMs - estimatedServerNow) / 1000))
}

export function formatRemainingTime(seconds: number): string {
  if (seconds <= 0) return 'Приём заявок завершён'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = seconds % 60
  if (hours > 0) return `${hours} ч ${minutes} мин`
  return `${minutes}:${String(secs).padStart(2, '0')}`
}

export function requestLinesAsText(request: PublicSupplyRequest): string {
  return request.lines.map((line) => line.raw_text).join('\n')
}
