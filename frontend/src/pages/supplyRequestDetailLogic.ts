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
