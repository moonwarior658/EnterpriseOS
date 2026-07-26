import {
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  layoutDashboardWidgets,
  type DashboardWidgetSize,
} from '../../pages/dashboardWidgetLogic'
import DashboardWidget from './DashboardWidget'
import {
  useFlipLayoutAnimation,
  usePrefersReducedMotion,
} from './useFlipLayoutAnimation'

export type DashboardWidgetDefinition = {
  id: string
  size: DashboardWidgetSize
  order: number
  content: ReactNode
}

const EXIT_DURATION_MS = 280

function DashboardGrid({
  widgets,
}: {
  widgets: DashboardWidgetDefinition[]
}) {
  const orderedWidgets = useMemo(
    () => [...widgets].sort((left, right) => left.order - right.order),
    [widgets],
  )
  const orderedWidgetsRef = useRef(orderedWidgets)
  const orderedWidgetKey = orderedWidgets
    .map((widget) => `${widget.id}:${widget.size}:${widget.order}`)
    .join('|')
  const [displayedWidgets, setDisplayedWidgets] =
    useState(orderedWidgets)
  const displayedWidgetsRef = useRef(displayedWidgets)
  const [exitingIds, setExitingIds] = useState<Set<string>>(new Set())
  const containerRef = useRef<HTMLDivElement>(null)
  const prefersReducedMotion = usePrefersReducedMotion()

  useEffect(() => {
    orderedWidgetsRef.current = orderedWidgets
  }, [orderedWidgets])

  useEffect(() => {
    let exitTimeout: number | undefined
    const updateTimeout = window.setTimeout(() => {
      const nextWidgets = orderedWidgetsRef.current
      const previousWidgets = displayedWidgetsRef.current
      const nextById = new Map(
        nextWidgets.map((widget) => [widget.id, widget]),
      )
      const removedIds = previousWidgets
        .filter((widget) => !nextById.has(widget.id))
        .map((widget) => widget.id)

      if (removedIds.length === 0 || prefersReducedMotion) {
        displayedWidgetsRef.current = nextWidgets
        setExitingIds(new Set())
        setDisplayedWidgets(nextWidgets)
        return
      }

      const previousIds = new Set(
        previousWidgets.map((widget) => widget.id),
      )
      const widgetsDuringExit = [
        ...previousWidgets.map(
          (widget) => nextById.get(widget.id) ?? widget,
        ),
        ...nextWidgets.filter((widget) => !previousIds.has(widget.id)),
      ]
      displayedWidgetsRef.current = widgetsDuringExit
      setDisplayedWidgets(widgetsDuringExit)
      setExitingIds(new Set(removedIds))
      exitTimeout = window.setTimeout(() => {
        const latestWidgets = orderedWidgetsRef.current
        displayedWidgetsRef.current = latestWidgets
        setDisplayedWidgets(latestWidgets)
        setExitingIds(new Set())
      }, EXIT_DURATION_MS)
    }, 0)

    return () => {
      window.clearTimeout(updateTimeout)
      if (exitTimeout !== undefined) {
        window.clearTimeout(exitTimeout)
      }
    }
  }, [orderedWidgetKey, prefersReducedMotion])

  const currentWidgetsById = new Map(
    orderedWidgets.map((widget) => [widget.id, widget]),
  )
  const renderedWidgets = displayedWidgets.map(
    (widget) => currentWidgetsById.get(widget.id) ?? widget,
  )
  const layout = layoutDashboardWidgets(renderedWidgets)
  const layoutById = new Map(layout.map((item) => [item.id, item]))
  const layoutKey = layout
    .map(
      (item) =>
        `${item.id}:${item.column}:${item.row}:${exitingIds.has(item.id)}`,
    )
    .join('|')

  useFlipLayoutAnimation(
    containerRef,
    layoutKey,
    prefersReducedMotion,
  )

  if (renderedWidgets.length === 0) {
    return null
  }

  return (
    <div
      className="dashboard-widget-grid"
      ref={containerRef}
      aria-label="Рабочие виджеты"
    >
      {renderedWidgets.map((widget) => {
        const position = layoutById.get(widget.id)
        if (!position) {
          return null
        }
        return (
          <DashboardWidget
            id={widget.id}
            isExiting={exitingIds.has(widget.id)}
            key={widget.id}
            size={widget.size}
            style={{
              gridColumn: `${position.column} / span ${position.columnSpan}`,
              gridRow: `${position.row} / span ${position.rowSpan}`,
            }}
          >
            {widget.content}
          </DashboardWidget>
        )
      })}
    </div>
  )
}

export default DashboardGrid
