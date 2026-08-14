import type {
  IikoMappingStatus,
  IikoLegalContour,
  IikoSyncStatus,
  IikoWarehouseDestinationType,
  IikoWarehouseMapping,
  IikoWarehouseRole,
} from '../services/iikoMapping'

export function deduplicateIikoWarehouseMappings(
  mappings: IikoWarehouseMapping[],
): IikoWarehouseMapping[] {
  return [...new Map(mappings.map((mapping) => [mapping.id, mapping])).values()]
}

export function acquireIikoStockSnapshotGuard(
  guard: { current: boolean },
): boolean {
  if (guard.current) return false
  guard.current = true
  return true
}

export function nextComboboxIndex(
  current: number,
  itemCount: number,
  direction: 1 | -1,
): number {
  if (itemCount === 0) return -1
  if (current < 0) return direction === 1 ? 0 : itemCount - 1
  return (current + direction + itemCount) % itemCount
}

export function iikoStockSnapshotStatusLabel(
  status: IikoSyncStatus,
): string {
  if (status === 'SUCCEEDED') return 'Остатки сняты'
  if (status === 'PARTIALLY_SUCCEEDED') return 'Остатки сняты частично'
  if (status === 'FAILED') return 'Остатки не сняты'
  return 'Снимаем остатки'
}

export function iikoMappingStatusLabel(status: IikoMappingStatus): string {
  return {
    UNMAPPED: 'Не сопоставлено',
    SUGGESTED: 'Предложено',
    CONFIRMED: 'Подтверждено',
    CONFLICT: 'Конфликт',
    IGNORED: 'Игнорируется',
  }[status]
}

export function iikoWarehouseRoleLabel(role: IikoWarehouseRole): string {
  return {
    MAIN: 'Основной',
    PACKAGING: 'Упаковка',
    HOUSEHOLD: 'Хозяйственный',
    FIXED_ASSETS: 'Основные средства',
    OTHER: 'Другой',
  }[role]
}

export function iikoWarehouseDestinationTypeLabel(
  destinationType: IikoWarehouseDestinationType,
): string {
  return {
    DESTINATION: 'Склад подразделения',
    SOURCE: 'Источник снабжения',
  }[destinationType]
}

export function iikoLegalContourLabel(
  contour: IikoLegalContour,
): string {
  return {
    IP: 'ИП',
    OOO: 'ООО',
  }[contour]
}

export function mappingActionLabel(status: IikoMappingStatus): string {
  return status === 'CONFIRMED' ? 'Заменить связь' : 'Подтвердить'
}
