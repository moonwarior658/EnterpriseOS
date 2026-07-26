import {
  type RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'
import {
  activeDirectionStatusText,
  dashboardAnimationMode,
  dashboardIndicatorVariant,
  type DashboardConnectionState,
  type DashboardIndicatorVariant,
} from '../../pages/dashboardWidgetLogic'
import { usePrefersReducedMotion } from './useFlipLayoutAnimation'

const STATUS_MOVE_DURATION_MS = 480
const STATUS_RETURN_DELAY_MS = 280

const INDICATOR_TEXT: Record<DashboardIndicatorVariant, string> = {
  checking: 'ПРОВЕРКА СВЯЗИ',
  healthy: 'ВСЁ ХОРОШО',
  attentionPulse: 'ТРЕБУЕТ ВНИМАНИЯ',
  attentionStable: 'ТРЕБУЕТ ВНИМАНИЯ',
  criticalPulse: 'ТРЕБУЕТ ВНИМАНИЯ',
  unavailable: 'НЕТ СВЯЗИ С СИСТЕМОЙ',
}

function useStatusPositionAnimation(
  statusRef: RefObject<HTMLElement | null>,
  position: 'centered' | 'workspace',
  prefersReducedMotion: boolean,
): void {
  const previousRect = useRef<DOMRect | null>(null)
  const activeAnimation = useRef<Animation | null>(null)

  useLayoutEffect(() => {
    const element = statusRef.current
    if (!element) {
      return
    }

    const nextRect = element.getBoundingClientRect()
    const oldRect = previousRect.current
    activeAnimation.current?.cancel()

    if (
      oldRect &&
      dashboardAnimationMode(prefersReducedMotion) === 'full'
    ) {
      const deltaX = oldRect.left - nextRect.left
      const deltaY = oldRect.top - nextRect.top
      if (Math.abs(deltaX) >= 0.5 || Math.abs(deltaY) >= 0.5) {
        activeAnimation.current = element.animate(
          [
            { transform: `translate(${deltaX}px, ${deltaY}px)` },
            { transform: 'translate(0, 0)' },
          ],
          {
            duration: STATUS_MOVE_DURATION_MS,
            easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
          },
        )
      }
    }

    previousRect.current = nextRect
  }, [position, prefersReducedMotion, statusRef])

  useEffect(
    () => () => {
      activeAnimation.current?.cancel()
    },
    [],
  )
}

function mainStatusText(
  connectionState: DashboardConnectionState,
  activeDirectionCount: number,
): string {
  if (connectionState === 'offline') {
    return 'СИСТЕМА НЕДОСТУПНА'
  }
  if (connectionState === 'checking') {
    return 'ПРОВЕРЯЕМ СИСТЕМУ'
  }
  if (activeDirectionCount === 0) {
    return 'ВСЁ НАХУЙ ХОРОШО'
  }
  return activeDirectionStatusText(activeDirectionCount)
}

function DashboardSystemStatus({
  activeDirectionCount,
  connectionState,
}: {
  activeDirectionCount: number
  connectionState: DashboardConnectionState
}) {
  const [displayedDirectionCount, setDisplayedDirectionCount] =
    useState(activeDirectionCount)
  const prefersReducedMotion = usePrefersReducedMotion()
  const statusRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const delay =
      activeDirectionCount === 0 && displayedDirectionCount > 0
        ? STATUS_RETURN_DELAY_MS
        : 0
    const timeout = window.setTimeout(
      () => setDisplayedDirectionCount(activeDirectionCount),
      delay,
    )
    return () => window.clearTimeout(timeout)
  }, [activeDirectionCount, displayedDirectionCount])

  const position =
    displayedDirectionCount > 0 ? 'workspace' : 'centered'
  const variant = dashboardIndicatorVariant(
    connectionState,
    displayedDirectionCount,
  )
  const text = mainStatusText(
    connectionState,
    displayedDirectionCount,
  )

  useStatusPositionAnimation(
    statusRef,
    position,
    prefersReducedMotion,
  )

  return (
    <div
      className={`dashboard-system-status-position dashboard-system-status-position--${position}`}
    >
      <div
        aria-live={
          connectionState === 'offline' ? 'assertive' : 'polite'
        }
        aria-atomic="true"
        className={`dashboard-system-status dashboard-system-status--${position}`}
        ref={statusRef}
        role="status"
      >
        <h1>{text}</h1>
        <div
          className={`dashboard-system-indicator dashboard-system-indicator--${variant}`}
        >
          {INDICATOR_TEXT[variant]}
        </div>
      </div>
    </div>
  )
}

export default DashboardSystemStatus
