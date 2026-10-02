import { useEffect, type ReactNode } from 'react'

type EosDialogProps = {
  title: string
  children: ReactNode
  onClose: () => void
  className?: string
}

export function EosDialog({ title, children, onClose, className = '' }: EosDialogProps) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return <div className="employee-dialog-backdrop" role="presentation" onMouseDown={(event) => {
    if (event.target === event.currentTarget) onClose()
  }}>
    <section className={`employee-dialog ${className}`.trim()} role="dialog" aria-modal="true" aria-label={title}>
      <h2>{title}</h2>
      {children}
    </section>
  </div>
}
