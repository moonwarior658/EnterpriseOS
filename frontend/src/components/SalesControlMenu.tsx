import { useEffect, useRef, useState } from 'react'

export default function SalesControlMenu({ label, items, disabled = false }: {
  label: string; items: { label: string; selected?: boolean; onSelect: () => void }[]; disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const container = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (!open) return
    const close = (event: PointerEvent) => { if (!container.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() } }
    document.addEventListener('pointerdown', close)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', close); document.removeEventListener('keydown', escape) }
  }, [open])
  return <div className="statistics-menu" ref={container}>
    <button ref={trigger} type="button" className="secondary-action" disabled={disabled} aria-expanded={open && !disabled} onClick={() => setOpen(!open)}>{label} <span aria-hidden="true">⌄</span></button>
    {open && !disabled && <div className="statistics-menu-options" aria-label={label}>{items.map(item => <button type="button" key={item.label} aria-pressed={item.selected} onClick={() => { setOpen(false); trigger.current?.focus(); item.onSelect() }}>{item.label}{item.selected && <span aria-hidden="true"> ✓</span>}</button>)}</div>}
  </div>
}
