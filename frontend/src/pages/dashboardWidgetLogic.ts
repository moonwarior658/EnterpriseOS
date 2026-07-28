import type { SupplyDashboardSummary } from '../services/supplyAdmin'

export type DashboardWidgetSize = '1x1' | '1x2' | '2x2'
export type DashboardConnectionState = 'checking' | 'online' | 'offline'
export type DashboardViewMode = 'empty' | 'active'
export type DashboardIndicatorVariant =
  | 'checking'
  | 'healthy'
  | 'attentionPulse'
  | 'attentionStable'
  | 'criticalPulse'
  | 'unavailable'

export type DashboardWidgetId =
  | 'warehouse-requests' | 'repair-requests'
  | 'supply-new' | 'supply-mapping' | 'supply-progress'
  | 'supply-debts' | 'supply-critical-debts'

export type DashboardWidgetConfig = {
  id: DashboardWidgetId
  size: DashboardWidgetSize
  order: number
  isVisible: boolean
}

export type DashboardSupplyWidgetCounts = {
  newRequests: number
  mappingRequired: number
  requestsInProgress: number
  activeDebts: number
  criticalDebts: number
}

export type DashboardWidgetLayoutItem = {
  id: string
  size: DashboardWidgetSize
  column: number
  row: number
  columnSpan: number
  rowSpan: number
}

export const DASHBOARD_GRID_MAX_COLUMNS = 9
export const DASHBOARD_GRID_MAX_ROWS = 9
export const DASHBOARD_AUTO_FLOW_ROWS = 3
export const DASHBOARD_EMPTY_TITLE = 'Всё спокойно'

const SIZE_SPANS: Record<
  DashboardWidgetSize,
  { columnSpan: number; rowSpan: number }
> = {
  '1x1': { columnSpan: 1, rowSpan: 1 },
  '1x2': { columnSpan: 1, rowSpan: 2 },
  '2x2': { columnSpan: 2, rowSpan: 2 },
}

const DASHBOARD_WIDGET_CONFIG = [
  {
    id: 'warehouse-requests',
    size: '1x1',
    order: 10,
  },
  {
    id: 'repair-requests',
    size: '1x1',
    order: 20,
  },
  { id: 'supply-new', size: '1x1', order: 30 },
  { id: 'supply-mapping', size: '1x1', order: 40 },
  { id: 'supply-progress', size: '1x1', order: 50 },
  { id: 'supply-debts', size: '1x1', order: 60 },
  { id: 'supply-critical-debts', size: '1x1', order: 70 },
] as const satisfies ReadonlyArray<
  Omit<DashboardWidgetConfig, 'isVisible'>
>

export function buildDashboardWidgetConfig(
  warehouseCount: number,
  repairCount: number,
  supply: DashboardSupplyWidgetCounts = {
    newRequests: 0,
    mappingRequired: 0,
    requestsInProgress: 0,
    activeDebts: 0,
    criticalDebts: 0,
  },
): DashboardWidgetConfig[] {
  const visibility: Record<DashboardWidgetId, boolean> = {
    'warehouse-requests': warehouseCount > 0,
    'repair-requests': repairCount > 0,
    'supply-new': supply.newRequests > 0,
    'supply-mapping': supply.mappingRequired > 0,
    'supply-progress': supply.requestsInProgress > 0,
    'supply-debts': supply.activeDebts > 0,
    'supply-critical-debts': supply.criticalDebts > 0,
  }

  return DASHBOARD_WIDGET_CONFIG.map((widget) => ({
    ...widget,
    isVisible: visibility[widget.id],
  }))
    .filter((widget) => widget.isVisible)
    .sort((left, right) => left.order - right.order)
}

export function supplySummaryToDashboardWidgetCounts(
  summary: SupplyDashboardSummary | null,
): DashboardSupplyWidgetCounts {
  return {
    newRequests: summary?.new_requests ?? 0,
    mappingRequired: summary?.mapping_required ?? 0,
    requestsInProgress: summary?.requests_in_progress ?? 0,
    activeDebts: summary?.active_debts ?? 0,
    criticalDebts: summary?.critical_debts ?? 0,
  }
}

export function dashboardWidgetSpan(
  size: DashboardWidgetSize,
): { columnSpan: number; rowSpan: number } {
  return SIZE_SPANS[size]
}

export function layoutDashboardWidgets(
  widgets: ReadonlyArray<{ id: string; size: DashboardWidgetSize }>,
  rowsPerColumn = DASHBOARD_AUTO_FLOW_ROWS,
  maxColumns = DASHBOARD_GRID_MAX_COLUMNS,
  maxRows = DASHBOARD_GRID_MAX_ROWS,
): DashboardWidgetLayoutItem[] {
  const occupied = new Set<string>()

  return widgets.map((widget) => {
    const span = dashboardWidgetSpan(widget.size)

    for (
      let bandStartRow = 1;
      bandStartRow <= maxRows;
      bandStartRow += rowsPerColumn
    ) {
      const bandEndRow = Math.min(
        bandStartRow + rowsPerColumn - 1,
        maxRows,
      )
      for (let column = 1; column <= maxColumns; column += 1) {
        for (
          let row = bandStartRow;
          row <= bandEndRow;
          row += 1
        ) {
          if (
            row + span.rowSpan - 1 > bandEndRow ||
            column + span.columnSpan - 1 > maxColumns
          ) {
            continue
          }

          const cells: string[] = []
          for (
            let columnOffset = 0;
            columnOffset < span.columnSpan;
            columnOffset += 1
          ) {
            for (
              let rowOffset = 0;
              rowOffset < span.rowSpan;
              rowOffset += 1
            ) {
              cells.push(
                `${column + columnOffset}:${row + rowOffset}`,
              )
            }
          }

          if (cells.some((cell) => occupied.has(cell))) {
            continue
          }

          cells.forEach((cell) => occupied.add(cell))
          return {
            id: widget.id,
            size: widget.size,
            column,
            row,
            ...span,
          }
        }
      }
    }

    throw new Error('Превышен логический предел Dashboard')
  })
}

export function dashboardAnimationMode(
  prefersReducedMotion: boolean,
): 'full' | 'reduced' {
  return prefersReducedMotion ? 'reduced' : 'full'
}

export function activeDashboardDirectionCount(
  widgets: ReadonlyArray<{ isVisible: boolean }>,
): number {
  return widgets.filter((widget) => widget.isVisible).length
}

export function dashboardViewMode(
  activeDirectionCount: number,
): DashboardViewMode {
  return activeDirectionCount === 0 ? 'empty' : 'active'
}

export function dashboardEmptySystemStatusText(
  connectionState: DashboardConnectionState,
  apiHealth: { service: string; version: string } | null,
): string {
  if (connectionState === 'checking') {
    return 'Проверяем состояние системы…'
  }
  if (connectionState === 'online' && apiHealth) {
    return `Система работает · ${apiHealth.service} v${apiHealth.version}`
  }
  return 'Нет соединения с ядром системы'
}

export function dashboardIndicatorVariant(
  connectionState: DashboardConnectionState,
  activeDirectionCount: number,
): DashboardIndicatorVariant {
  if (connectionState === 'offline') {
    return 'unavailable'
  }
  if (connectionState === 'checking') {
    return 'checking'
  }
  if (activeDirectionCount === 0) {
    return 'healthy'
  }
  if (activeDirectionCount <= 2) {
    return 'attentionPulse'
  }
  if (activeDirectionCount <= 4) {
    return 'attentionStable'
  }
  return 'criticalPulse'
}

export function activeDirectionNoun(count: number): string {
  const mod100 = count % 100
  const mod10 = count % 10

  if (mod100 >= 11 && mod100 <= 14) {
    return 'направлений'
  }
  if (mod10 === 1) {
    return 'направление'
  }
  if (mod10 >= 2 && mod10 <= 4) {
    return 'направления'
  }
  return 'направлений'
}

export function activeDirectionStatusText(count: number): string {
  const verb = count === 1 ? 'Требует' : 'Требуют'
  return `${verb} внимания ${count} ${activeDirectionNoun(count)}`
}
