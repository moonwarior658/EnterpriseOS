import assert from 'node:assert/strict'
import test from 'node:test'
import {
  activeDashboardDirectionCount,
  activeDirectionNoun,
  activeDirectionStatusText,
  buildDashboardWidgetConfig,
  DASHBOARD_EMPTY_TITLE,
  dashboardAnimationMode,
  dashboardEmptySystemStatusText,
  dashboardIndicatorVariant,
  dashboardViewMode,
  dashboardWidgetSpan,
  layoutDashboardWidgets,
  type DashboardWidgetSize,
} from '../src/pages/dashboardWidgetLogic.ts'

function widgets(
  count: number,
  size: DashboardWidgetSize = '1x1',
) {
  return Array.from({ length: count }, (_, index) => ({
    id: `widget-${index + 1}`,
    size,
  }))
}

test('складской блок скрыт при нулевом количестве', () => {
  const result = buildDashboardWidgetConfig(0, 2)
  assert.equal(
    result.some((widget) => widget.id === 'warehouse-requests'),
    false,
  )
})

test('ремонтный блок скрыт при нулевом количестве', () => {
  const result = buildDashboardWidgetConfig(2, 0)
  assert.equal(
    result.some((widget) => widget.id === 'repair-requests'),
    false,
  )
})

test('блок появляется при положительном количестве', () => {
  assert.deepEqual(
    buildDashboardWidgetConfig(1, 0).map((widget) => widget.id),
    ['warehouse-requests'],
  )
  assert.deepEqual(
    buildDashboardWidgetConfig(0, 1).map((widget) => widget.id),
    ['repair-requests'],
  )
})

test('порядок виджетов стабилен', () => {
  assert.deepEqual(
    buildDashboardWidgetConfig(3, 4).map((widget) => widget.id),
    ['warehouse-requests', 'repair-requests'],
  )
})

test('Supply-виджеты скрывают нули и ведут критические долги последними', () => {
  const result = buildDashboardWidgetConfig(0, 0, {
    newRequests: 2,
    mappingRequired: 1,
    requestsInProgress: 3,
    activeDebts: 4,
    criticalDebts: 1,
  })
  assert.deepEqual(
    result.map((widget) => widget.id),
    [
      'supply-new',
      'supply-mapping',
      'supply-progress',
      'supply-debts',
      'supply-critical-debts',
    ],
  )
})

test('размер 1x1 занимает одну логическую ячейку', () => {
  assert.deepEqual(dashboardWidgetSpan('1x1'), {
    columnSpan: 1,
    rowSpan: 1,
  })
})

test('после третьей строки размещение переходит в следующий столбец', () => {
  const layout = layoutDashboardWidgets(widgets(4))
  assert.deepEqual(
    layout.map(({ column, row }) => [column, row]),
    [
      [1, 1],
      [1, 2],
      [1, 3],
      [2, 1],
    ],
  )
})

test('после девяти столбцов размещение продолжает следующую полосу строк', () => {
  const layout = layoutDashboardWidgets(widgets(28))
  assert.deepEqual(
    [layout[27].column, layout[27].row],
    [1, 4],
  )
})

test('скрытый блок исключается из layout', () => {
  const visible = buildDashboardWidgetConfig(0, 1)
  assert.deepEqual(
    layoutDashboardWidgets(visible).map((widget) => widget.id),
    ['repair-requests'],
  )
})

test('последующие блоки занимают освободившееся место', () => {
  const initial = layoutDashboardWidgets(widgets(4))
  const afterRemoval = layoutDashboardWidgets(widgets(4).slice(1))

  assert.deepEqual(
    [initial[1].column, initial[1].row],
    [1, 2],
  )
  assert.deepEqual(
    [afterRemoval[0].column, afterRemoval[0].row],
    [1, 1],
  )
})

test('крупные виджеты не пересекаются с соседними', () => {
  const layout = layoutDashboardWidgets([
    { id: 'large', size: '2x2' },
    { id: 'compact', size: '1x1' },
    { id: 'vertical', size: '1x2' },
  ])

  assert.deepEqual(
    layout.map(({ id, column, row }) => [id, column, row]),
    [
      ['large', 1, 1],
      ['compact', 1, 3],
      ['vertical', 3, 1],
    ],
  )
})

test('prefers-reduced-motion отключает полный режим анимации', () => {
  assert.equal(dashboardAnimationMode(false), 'full')
  assert.equal(dashboardAnimationMode(true), 'reduced')
})

test('выбирает вариант индикатора по числу активных направлений', () => {
  assert.equal(dashboardIndicatorVariant('online', 0), 'healthy')
  assert.equal(
    dashboardIndicatorVariant('online', 1),
    'attentionPulse',
  )
  assert.equal(
    dashboardIndicatorVariant('online', 2),
    'attentionPulse',
  )
  assert.equal(
    dashboardIndicatorVariant('online', 3),
    'attentionStable',
  )
  assert.equal(
    dashboardIndicatorVariant('online', 4),
    'attentionStable',
  )
  assert.equal(
    dashboardIndicatorVariant('online', 5),
    'criticalPulse',
  )
  assert.equal(
    dashboardIndicatorVariant('online', 10),
    'criticalPulse',
  )
})

test('offline имеет приоритет при любом количестве направлений', () => {
  assert.equal(dashboardIndicatorVariant('offline', 0), 'unavailable')
  assert.equal(dashboardIndicatorVariant('offline', 10), 'unavailable')
})

test('склоняет количество активных направлений', () => {
  assert.equal(activeDirectionNoun(1), 'направление')
  assert.equal(activeDirectionNoun(2), 'направления')
  assert.equal(activeDirectionNoun(5), 'направлений')
  assert.equal(activeDirectionNoun(11), 'направлений')
  assert.equal(activeDirectionNoun(21), 'направление')
  assert.equal(activeDirectionNoun(22), 'направления')
  assert.equal(
    activeDirectionStatusText(1),
    'Требует внимания 1 направление',
  )
  assert.equal(
    activeDirectionStatusText(22),
    'Требуют внимания 22 направления',
  )
})

test('число направлений равно числу видимых виджетов, а не заявок', () => {
  const fiveWarehouseRequests = buildDashboardWidgetConfig(5, 0)
  const warehouseAndRepairRequests =
    buildDashboardWidgetConfig(5, 12)

  assert.equal(
    activeDashboardDirectionCount(fiveWarehouseRequests),
    1,
  )
  assert.equal(
    activeDashboardDirectionCount(warehouseAndRepairRequests),
    2,
  )
})

test('при нуле видимых виджетов выбирается спокойное пустое состояние', () => {
  assert.equal(dashboardViewMode(0), 'empty')
  assert.equal(DASHBOARD_EMPTY_TITLE, 'Всё спокойно')
  assert.notEqual(DASHBOARD_EMPTY_TITLE, 'ВСЁ НАХУЙ ХОРОШО')
})

test('нижний системный статус отражает проверку, работу и offline', () => {
  assert.equal(
    dashboardEmptySystemStatusText('checking', null),
    'Проверяем состояние системы…',
  )
  assert.equal(
    dashboardEmptySystemStatusText('online', {
      service: 'enterpriseos-api',
      version: '1.2.3',
    }),
    'Система работает · enterpriseos-api v1.2.3',
  )
  assert.equal(
    dashboardEmptySystemStatusText('offline', null),
    'Нет соединения с ядром системы',
  )
})

test('при наличии виджетов сохраняется активное состояние', () => {
  assert.equal(dashboardViewMode(1), 'active')
  assert.equal(dashboardViewMode(2), 'active')
})
