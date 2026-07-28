import {
  forwardRef,
  type InputHTMLAttributes,
  type SelectHTMLAttributes,
} from 'react'

type SelectProps = SelectHTMLAttributes<HTMLSelectElement>

export const EosSelect = forwardRef<HTMLSelectElement, SelectProps>(
  function EosSelect({ className = '', ...props }, ref) {
    return (
      <span className={`eos-select ${className}`.trim()}>
        <select ref={ref} {...props} />
        <span className="eos-select-arrow" aria-hidden="true">⌄</span>
      </span>
    )
  },
)

type CheckboxProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'type'
> & { label: string }

export const EosCheckbox = forwardRef<HTMLInputElement, CheckboxProps>(
  function EosCheckbox({ className = '', label, ...props }, ref) {
    return (
      <label className={`eos-checkbox ${className}`.trim()}>
        <input ref={ref} type="checkbox" {...props} />
        <span className="eos-checkbox-mark" aria-hidden="true" />
        <span>{label}</span>
      </label>
    )
  },
)

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { label?: string }

export const EosDateField = forwardRef<HTMLInputElement, FieldProps>(
  function EosDateField({ className = '', label, ...props }, ref) {
    return (
      <label className={`eos-field ${className}`.trim()}>
        {label && <span>{label}</span>}
        <input ref={ref} type="date" {...props} />
      </label>
    )
  },
)

export const EosSearchField = forwardRef<HTMLInputElement, FieldProps>(
  function EosSearchField({ className = '', label, ...props }, ref) {
    return (
      <label className={`eos-field eos-search-field ${className}`.trim()}>
        {label && <span>{label}</span>}
        <input ref={ref} type="search" {...props} />
      </label>
    )
  },
)

type PaginationProps = {
  offset: number
  total: number
  pageSize: number
  itemCount: number
  onPageChange: (offset: number) => void
}

export function EosPagination({
  offset,
  total,
  pageSize,
  itemCount,
  onPageChange,
}: PaginationProps) {
  const page = Math.floor(offset / pageSize) + 1
  const isFirstPage = offset === 0
  const isLastPage = offset + itemCount >= total
  const range = total === 0
    ? '0 из 0'
    : `${offset + 1}–${offset + itemCount} из ${total}`

  return (
    <nav className="eos-pagination" aria-label="Пагинация реестра заявок">
      <div className="eos-pagination-controls">
        <button
          type="button"
          aria-label="Предыдущая страница"
          disabled={isFirstPage}
          onClick={() => onPageChange(Math.max(0, offset - pageSize))}
        >
          ←
        </button>
        <span className="eos-pagination-page" aria-current="page">{page}</span>
        <button
          type="button"
          aria-label="Следующая страница"
          disabled={isLastPage}
          onClick={() => onPageChange(offset + pageSize)}
        >
          →
        </button>
      </div>
      <span className="eos-pagination-range">{range}</span>
    </nav>
  )
}
