import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildDashboardWidgetConfig,
  dashboardAnimationMode,
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
