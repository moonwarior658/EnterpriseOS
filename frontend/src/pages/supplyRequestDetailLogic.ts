import type { SupplyLine, SupplyProduct } from '../services/supplyAdmin'

export type SupplyLineMappingDraft = {
  searchQuery: string
  productId: string
  selectedProduct: SupplyProduct | null
  unitId: string
  quantity: string
  status: 'idle' | 'loading' | 'error'
  error: string
}

export type SupplyLineMappingState = Record<string, SupplyLineMappingDraft>

export type SupplyLineWorkingDraft = {
  workingName: string
  quantity: string
  unitId: string
  status: 'idle' | 'loading' | 'error'
  error: string
}

export type SupplyLineWorkingState = Record<string, SupplyLineWorkingDraft>

export type SupplyWorkingSaveResult = {
  requestVersion: number
  savedLines: Record<string, SupplyLine>
  remaining: SupplyLineWorkingState
  errors: Record<string, unknown>
}

export const SUPPLY_MATCH_REQUIRED_STATUSES = [
  'UNPROCESSED',
  'PARSED',
  'NEEDS_REVIEW',
] as const

export function requiresSupplyLineMatch(line: SupplyLine): boolean {
  return SUPPLY_MATCH_REQUIRED_STATUSES.includes(
    line.match_status as (typeof SUPPLY_MATCH_REQUIRED_STATUSES)[number],
  )
}

export function supplyMatchProgress(lines: SupplyLine[]): {
  matched: number
  total: number
  needsReview: number
} {
  return {
    matched: lines.filter((line) => line.match_status === 'MATCHED').length,
    total: lines.length,
    needsReview: lines.filter(requiresSupplyLineMatch).length,
  }
}

export function nextSupplyLineToMatch(
  lines: SupplyLine[],
  completedLineId: string,
): string | null {
  const completedIndex = lines.findIndex((line) => line.id === completedLineId)
  const after = lines.slice(completedIndex + 1).find(requiresSupplyLineMatch)
  return after?.id ?? lines.find(requiresSupplyLineMatch)?.id ?? null
}

const SUPPLY_QUANTITY_SCALE = 1000

export function supplyQuantityMillis(value: string): number | null {
  const normalized = value.trim()
  if (!normalized) return 0
  const match = /^(\d+)(?:\.(\d{1,3}))?$/.exec(normalized)
  if (!match) return null
  const whole = Number(match[1])
  const fraction = Number((match[2] ?? '').padEnd(3, '0'))
  const result = whole * SUPPLY_QUANTITY_SCALE + fraction
  return Number.isSafeInteger(result) ? result : null
}

export function formatSupplyQuantityMillis(value: number): string {
  return (value / SUPPLY_QUANTITY_SCALE).toFixed(3)
}

export function supplyExpectedDebtMillis(
  requestedQuantity: string,
  sendQuantity: string,
): number | null {
  const requested = supplyQuantityMillis(requestedQuantity)
  const sent = supplyQuantityMillis(sendQuantity)
  if (requested === null || sent === null) return null
  return Math.max(requested - sent, 0)
}

export function supplySendExcessMillis(
  requestedQuantity: string,
  sendQuantity: string,
): number | null {
  const requested = supplyQuantityMillis(requestedQuantity)
  const sent = supplyQuantityMillis(sendQuantity)
  if (requested === null || sent === null) return null
  return Math.max(sent - requested, 0)
}

const TRAILING_QUANTITY_AND_UNIT = new RegExp(
  String.raw`\s+\d+(?:[.,]\d+)?\s*(?:кг|килограмм(?:а|ов)?|г|грамм(?:а|ов)?|л|литр(?:а|ов)?|шт|штук(?:а|и)?|уп|упаков(?:ка|ки|ок)|короб(?:ка|ки|ок)|рулон(?:а|ов)?)\.?\s*$`,
  'iu',
)

export function suggestSupplyWorkingName(
  parsedName: string | null,
  rawText: string,
): string {
  if (parsedName?.trim()) return parsedName.trim()
  return rawText.trim().replace(TRAILING_QUANTITY_AND_UNIT, '').trim()
}

export function createSupplyLineWorkingDraft(
  workingName: string,
  quantity: string,
  unitId: string,
): SupplyLineWorkingDraft {
  return {
    workingName,
    quantity,
    unitId,
    status: 'idle',
    error: '',
  }
}

export function getSupplyLineWorkingDraft(
  state: SupplyLineWorkingState,
  lineId: string,
  fallback: SupplyLineWorkingDraft,
): SupplyLineWorkingDraft {
  return state[lineId] ?? fallback
}

export function updateSupplyLineWorkingDraft(
  state: SupplyLineWorkingState,
  lineId: string,
  fallback: SupplyLineWorkingDraft,
  changes: Partial<SupplyLineWorkingDraft>,
): SupplyLineWorkingState {
  return {
    ...state,
    [lineId]: {
      ...(state[lineId] ?? fallback),
      ...changes,
    },
  }
}

export function clearSupplyLineWorkingDraft(
  state: SupplyLineWorkingState,
  lineId: string,
): SupplyLineWorkingState {
  const next = { ...state }
  delete next[lineId]
  return next
}

export function supplyLineWorkingBaseline(
  line: SupplyLine,
): SupplyLineWorkingDraft {
  return createSupplyLineWorkingDraft(
    line.working_name,
    line.send_quantity ?? line.quantity ?? line.parsed_quantity ?? '',
    line.requested_unit?.id ?? line.parsed_unit?.id ?? '',
  )
}

export function isSupplyLineWorkingDraftDirty(
  draft: SupplyLineWorkingDraft,
  baseline: SupplyLineWorkingDraft,
): boolean {
  return draft.workingName.trim() !== baseline.workingName.trim()
    || supplyQuantityMillis(draft.quantity)
      !== supplyQuantityMillis(baseline.quantity)
    || draft.unitId !== baseline.unitId
}

export async function saveDirtySupplyLines(
  requestId: string,
  requestVersion: number,
  lines: SupplyLine[],
  state: SupplyLineWorkingState,
  save: (
    requestId: string,
    lineId: string,
    input: {
      request_version: number
      working_name: string
      requested_quantity: string | null
      send_quantity: string
      requested_unit_id: string
    },
  ) => Promise<{ request_version: number; line: SupplyLine }>,
): Promise<SupplyWorkingSaveResult> {
  let currentVersion = requestVersion
  const remaining = { ...state }
  const savedLines: Record<string, SupplyLine> = {}
  const errors: Record<string, unknown> = {}

  for (const line of lines) {
    const draft = state[line.id]
    if (
      !draft
      || !isSupplyLineWorkingDraftDirty(
        draft,
        supplyLineWorkingBaseline(line),
      )
    ) continue
    try {
      const result = await save(requestId, line.id, {
        request_version: currentVersion,
        working_name: draft.workingName.trim(),
        requested_quantity:
          line.quantity ?? line.parsed_quantity ?? draft.quantity,
        send_quantity: draft.quantity,
        requested_unit_id: draft.unitId,
      })
      currentVersion = result.request_version
      savedLines[line.id] = result.line
      delete remaining[line.id]
    } catch (error) {
      errors[line.id] = error
    }
  }

  return {
    requestVersion: currentVersion,
    savedLines,
    remaining,
    errors,
  }
}

export function createSupplyLineMappingDraft(
  searchQuery: string,
  unitId: string,
  quantity: string,
): SupplyLineMappingDraft {
  return {
    searchQuery,
    productId: '',
    selectedProduct: null,
    unitId,
    quantity,
    status: 'idle',
    error: '',
  }
}

export function getSupplyLineMappingDraft(
  state: SupplyLineMappingState,
  lineId: string,
  searchQuery: string,
  unitId: string,
  quantity: string,
): SupplyLineMappingDraft {
  return state[lineId] ?? createSupplyLineMappingDraft(
    searchQuery,
    unitId,
    quantity,
  )
}

export function updateSupplyLineMappingDraft(
  state: SupplyLineMappingState,
  lineId: string,
  fallback: SupplyLineMappingDraft,
  changes: Partial<SupplyLineMappingDraft>,
): SupplyLineMappingState {
  return {
    ...state,
    [lineId]: {
      ...(state[lineId] ?? fallback),
      ...changes,
    },
  }
}

export function clearSupplyLineMappingDraft(
  state: SupplyLineMappingState,
  lineId: string,
): SupplyLineMappingState {
  const next = { ...state }
  delete next[lineId]
  return next
}
