import {
  type RefObject,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react'
import { dashboardAnimationMode } from '../../pages/dashboardWidgetLogic'

const FLIP_DURATION_MS = 320

export function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(() =>
    typeof window === 'undefined'
      ? false
      : window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  )

  useEffect(() => {
    const mediaQuery = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    )
    const handleChange = () => setPrefersReducedMotion(mediaQuery.matches)

    handleChange()
    mediaQuery.addEventListener('change', handleChange)
    return () => mediaQuery.removeEventListener('change', handleChange)
  }, [])

  return prefersReducedMotion
}

export function useFlipLayoutAnimation(
  containerRef: RefObject<HTMLElement | null>,
  layoutKey: string,
  prefersReducedMotion: boolean,
): void {
  const previousRects = useRef(new Map<string, DOMRect>())
  const animations = useRef<Animation[]>([])

  useLayoutEffect(() => {
    const container = containerRef.current
    if (!container) {
      return
    }

    animations.current.forEach((animation) => animation.cancel())
    animations.current = []

    const elements = Array.from(
      container.querySelectorAll<HTMLElement>('[data-dashboard-widget-id]'),
    )
    const nextRects = new Map<string, DOMRect>()

    elements.forEach((element) => {
      const id = element.dataset.dashboardWidgetId
      if (id) {
        nextRects.set(id, element.getBoundingClientRect())
      }
    })

    if (dashboardAnimationMode(prefersReducedMotion) === 'full') {
      elements.forEach((element) => {
        const id = element.dataset.dashboardWidgetId
        const previousRect = id ? previousRects.current.get(id) : undefined
        const nextRect = id ? nextRects.get(id) : undefined
        if (!previousRect || !nextRect) {
          return
        }

        const deltaX = previousRect.left - nextRect.left
        const deltaY = previousRect.top - nextRect.top
        if (Math.abs(deltaX) < 0.5 && Math.abs(deltaY) < 0.5) {
          return
        }

        animations.current.push(
          element.animate(
            [
              { transform: `translate(${deltaX}px, ${deltaY}px)` },
              { transform: 'translate(0, 0)' },
            ],
            {
              duration: FLIP_DURATION_MS,
              easing: 'cubic-bezier(0.22, 1, 0.36, 1)',
            },
          ),
        )
      })
    }

    previousRects.current = nextRects
  }, [containerRef, layoutKey, prefersReducedMotion])

  useEffect(
    () => () => {
      animations.current.forEach((animation) => animation.cancel())
    },
    [],
  )
}
