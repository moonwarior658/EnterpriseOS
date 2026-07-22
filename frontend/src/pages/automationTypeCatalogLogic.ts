import type {
  AutomationSchedule,
  AutomationType,
} from '../services/automation.ts'

export type AutomationTypeOption = {
  key: string
  displayName: string
  description: string
  isLegacy: boolean
}

export type AutomationTypeLoadResult =
  | { status: 'success'; types: AutomationType[] }
  | { status: 'error'; message: string }

export async function loadAutomationTypeCatalog(
  load: () => Promise<AutomationType[]>,
): Promise<AutomationTypeLoadResult> {
  try {
    return { status: 'success', types: await load() }
  } catch {
    return {
      status: 'error',
      message: 'Не удалось загрузить типы автоматизаций. Попробуйте ещё раз',
    }
  }
}

export function automationTypeOptions(
  types: AutomationType[],
  currentKey?: string,
): AutomationTypeOption[] {
  const options = types.map((item) => ({
    key: item.key,
    displayName: item.display_name,
    description: item.description,
    isLegacy: false,
  }))

  if (currentKey && !types.some((item) => item.key === currentKey)) {
    options.push({
      key: currentKey,
      displayName: `${currentKey} (недоступный тип)`,
      description: 'Выберите поддерживаемый тип перед сохранением.',
      isLegacy: true,
    })
  }

  return options
}

export function automationTypeDisplayName(
  types: AutomationType[],
  key: string,
): string {
  return types.find((item) => item.key === key)?.display_name ?? key
}

export function matchesAutomationType(
  schedule: AutomationSchedule,
  key: string,
): boolean {
  return key === 'all' || schedule.automation_type === key
}
