import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

type EosDialogProps = {
  title: string
  children: ReactNode
  onClose: () => void
  className?: string
}

type ScrollLockSnapshot = {
  htmlOverflow: string
  bodyOverflow: string
  bodyPaddingRight: string
  scrollY: number
}

let openDialogCount = 0
let scrollLockSnapshot: ScrollLockSnapshot | null = null

export function EosDialog({ title, children, onClose, className = '' }: EosDialogProps) {
  const onCloseRef = useRef(onClose)
  useEffect(() => { onCloseRef.current = onClose }, [onClose])

  useEffect(() => {
    if (openDialogCount === 0) {
      const html = document.documentElement
      const body = document.body
      const scrollbarWidth = window.innerWidth - html.clientWidth
      scrollLockSnapshot = {
        htmlOverflow: html.style.overflow,
        bodyOverflow: body.style.overflow,
        bodyPaddingRight: body.style.paddingRight,
        scrollY: window.scrollY,
      }
      html.style.overflow = 'hidden'
      body.style.overflow = 'hidden'
      if (scrollbarWidth > 0) {
        body.style.paddingRight = `${parseFloat(getComputedStyle(body).paddingRight) + scrollbarWidth}px`
      }
    }
    openDialogCount += 1
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      window.removeEventListener('keydown', closeOnEscape)
      openDialogCount -= 1
      if (openDialogCount === 0 && scrollLockSnapshot) {
        document.documentElement.style.overflow = scrollLockSnapshot.htmlOverflow
        document.body.style.overflow = scrollLockSnapshot.bodyOverflow
        document.body.style.paddingRight = scrollLockSnapshot.bodyPaddingRight
        window.scrollTo(0, scrollLockSnapshot.scrollY)
        scrollLockSnapshot = null
      }
    }
  }, [])

  return createPortal(<div className="employee-dialog-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <section className={`employee-dialog ${className}`.trim()} role="dialog" aria-modal="true" aria-label={title}>
      <h2>{title}</h2>
      {children}
    </section>
  </div>, document.body)
}
