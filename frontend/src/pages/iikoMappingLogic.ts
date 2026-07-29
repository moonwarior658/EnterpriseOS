import type {
  IikoMappingStatus,
  IikoWarehouseDestinationType,
  IikoWarehouseRole,
  IikoWarehouseSourceDirection,
} from '../services/iikoMapping'

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

export function iikoWarehouseSourceDirectionLabel(
  direction: IikoWarehouseSourceDirection,
): string {
  return {
    PRODUCT: 'Продукты',
    PACKAGING: 'Упаковка',
    HOUSEHOLD: 'Хозяйственные товары',
    FIXED_ASSETS: 'Основные средства',
  }[direction]
}

export function mappingActionLabel(status: IikoMappingStatus): string {
  return status === 'CONFIRMED' ? 'Заменить связь' : 'Подтвердить'
}
