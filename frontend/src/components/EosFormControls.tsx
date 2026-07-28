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
