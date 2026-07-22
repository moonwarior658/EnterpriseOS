import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  AutomationSchedule,
  AutomationType,
} from '../src/services/automation.ts'
import {
  automationTypeDisplayName,
  automationTypeOptions,
  loadAutomationTypeCatalog,
  matchesAutomationType,
} from '../src/pages/automationTypeCatalogLogic.ts'

const TYPES: AutomationType[] = [
  {
    key: 'smoke_test',
    display_name: 'Проверка Automation Core',
    description: 'Безопасная техническая проверка.',
    category: 'technical',
    is_system: true,
    supports_manual_run: true,
  },
]

const SCHEDULE = {
  id: 42,
  automation_type: 'smoke_test',
} as AutomationSchedule

test('успешно загружает каталог и сохраняет пустой каталог', async () => {
  const loaded = await loadAutomationTypeCatalog(async () => TYPES)
  const empty = await loadAutomationTypeCatalog(async () => [])

  assert.deepEqual(loaded, { status: 'success', types: TYPES })
  assert.deepEqual(empty, { status: 'success', types: [] })
})

test('возвращает безопасную ошибку загрузки каталога', async () => {
  const result = await loadAutomationTypeCatalog(async () => {
    throw new Error('token at internal webhook')
  })

  assert.deepEqual(result, {
    status: 'error',
    message: 'Не удалось загрузить типы автоматизаций. Попробуйте ещё раз',
  })
  assert.equal(JSON.stringify(result).includes('token'), false)
})

test('select показывает display_name, но сохраняет key', () => {
  const options = automationTypeOptions(TYPES)

  assert.deepEqual(options[0], {
    key: 'smoke_test',
    displayName: 'Проверка Automation Core',
    description: 'Безопасная техническая проверка.',
    isLegacy: false,
  })
})

test('не подменяет неизвестный legacy key', () => {
  const options = automationTypeOptions(TYPES, 'legacy_type')

  assert.equal(options.at(-1)?.key, 'legacy_type')
  assert.equal(options.at(-1)?.isLegacy, true)
})

test('таблица показывает display_name и fallback для неизвестного key', () => {
  assert.equal(
    automationTypeDisplayName(TYPES, 'smoke_test'),
    'Проверка Automation Core',
  )
  assert.equal(automationTypeDisplayName(TYPES, 'legacy_type'), 'legacy_type')
})

test('фильтр сравнивает значения по key', () => {
  assert.equal(matchesAutomationType(SCHEDULE, 'all'), true)
  assert.equal(matchesAutomationType(SCHEDULE, 'smoke_test'), true)
  assert.equal(matchesAutomationType(SCHEDULE, 'legacy_type'), false)
})
