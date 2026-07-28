export type SupplyLineMappingDraft = {
  searchQuery: string
  productId: string
  unitId: string
  quantity: string
  saveAlias: boolean
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

export function createSupplyLineMappingDraft(
  unitId: string,
  quantity: string,
): SupplyLineMappingDraft {
  return {
    searchQuery: '',
    productId: '',
    unitId,
    quantity,
    saveAlias: false,
    status: 'idle',
    error: '',
  }
}

export function getSupplyLineMappingDraft(
  state: SupplyLineMappingState,
  lineId: string,
  unitId: string,
  quantity: string,
): SupplyLineMappingDraft {
  return state[lineId] ?? createSupplyLineMappingDraft(unitId, quantity)
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
