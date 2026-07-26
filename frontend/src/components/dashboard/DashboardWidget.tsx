import type { ReactNode } from 'react'
import type { DashboardWidgetSize } from '../../pages/dashboardWidgetLogic'

type DashboardWidgetProps = {
  id: string
  size: DashboardWidgetSize
  isExiting?: boolean
  children: ReactNode
  style: {
    gridColumn: string
    gridRow: string
  }
}

function DashboardWidget({
  id,
  size,
  isExiting = false,
  children,
  style,
}: DashboardWidgetProps) {
  return (
    <article
      className={`dashboard-widget dashboard-widget-${size}${isExiting ? ' dashboard-widget-exiting' : ''}`}
      data-dashboard-widget-id={id}
      style={style}
    >
      {children}
    </article>
  )
}

export default DashboardWidget
