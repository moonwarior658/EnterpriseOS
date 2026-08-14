import { useEffect, useRef, useState } from 'react'
import {
  getSupplyProducts,
  type SupplyProduct,
} from '../services/supplyAdmin'
import { nextComboboxIndex } from '../pages/iikoMappingLogic'
import { EosSearchField } from './EosFormControls'

type EosProductComboboxProps = {
  id: string
  value: string
  selectedLabel: string
  disabled?: boolean
  onChange: (product: SupplyProduct) => void
}

export function EosProductCombobox({
  id,
  value,
  selectedLabel,
  disabled = false,
  onChange,
}: EosProductComboboxProps) {
  const rootRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(selectedLabel)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [dropdownPlacement, setDropdownPlacement] = useState<'above' | 'below'>(
    'below',
  )
  const [dropdownMaxHeight, setDropdownMaxHeight] = useState(272)
  const [searchResult, setSearchResult] = useState<{
    query: string
    items: SupplyProduct[]
    state: 'idle' | 'loading' | 'error'
  }>({ query: '', items: [], state: 'idle' })
  const normalizedQuery = query.trim()
  const currentResult = searchResult.query === normalizedQuery
    ? searchResult
    : { query: normalizedQuery, items: [], state: 'idle' as const }
  const listboxId = `${id}-options`
  const activeOptionId = activeIndex >= 0
    ? `${id}-option-${activeIndex}`
    : undefined

  function openDropdown() {
    const bounds = rootRef.current?.getBoundingClientRect()
    if (bounds) {
      const availableBelow = Math.max(0, window.innerHeight - bounds.bottom - 8)
      const availableAbove = Math.max(0, bounds.top - 8)
      const placement = availableBelow >= Math.min(272, availableAbove)
        ? 'below'
        : 'above'
      setDropdownPlacement(placement)
      setDropdownMaxHeight(Math.min(
        272,
        placement === 'below' ? availableBelow : availableAbove,
      ))
    }
    setOpen(true)
  }

  useEffect(() => {
    if (!open || normalizedQuery.length < 2) return

    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      setSearchResult({
        query: normalizedQuery,
        items: [],
        state: 'loading',
      })
      getSupplyProducts(normalizedQuery, controller.signal).then((page) => {
        if (controller.signal.aborted) return
        setSearchResult({
          query: normalizedQuery,
          items: page.items.slice(0, 20),
          state: 'idle',
        })
        setActiveIndex(page.items.length > 0 ? 0 : -1)
      }).catch(() => {
        if (controller.signal.aborted) return
        setSearchResult({
          query: normalizedQuery,
          items: [],
          state: 'error',
        })
        setActiveIndex(-1)
      })
    }, 300)

    return () => {
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [normalizedQuery, open])

  function selectProduct(product: SupplyProduct) {
    onChange(product)
    setQuery(product.name)
    setOpen(false)
    setActiveIndex(-1)
    inputRef.current?.focus()
  }

  return (
    <div
      className="eos-product-combobox"
      ref={rootRef}
      onBlur={(event) => {
        const next = event.relatedTarget
        if (!(next instanceof Node) || !rootRef.current?.contains(next)) {
          setQuery(selectedLabel)
          setOpen(false)
          setActiveIndex(-1)
        }
      }}
    >
      <EosSearchField
        ref={inputRef}
        aria-label="Поиск EOS-товара"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={activeOptionId}
        autoComplete="off"
        placeholder="Введите минимум 2 символа"
        value={open ? query : selectedLabel}
        disabled={disabled}
        onFocus={() => {
          setQuery(selectedLabel)
          openDropdown()
        }}
        onChange={(event) => {
          setQuery(event.target.value)
          openDropdown()
          setActiveIndex(-1)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            setQuery(selectedLabel)
            setOpen(false)
            setActiveIndex(-1)
            return
          }
          if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
            event.preventDefault()
            openDropdown()
            setActiveIndex((current) => nextComboboxIndex(
              current,
              currentResult.items.length,
              event.key === 'ArrowDown' ? 1 : -1,
            ))
            return
          }
          if (event.key === 'Enter' && open && activeIndex >= 0) {
            const product = currentResult.items[activeIndex]
            if (product) {
              event.preventDefault()
              selectProduct(product)
            }
          }
        }}
      />
      {open && normalizedQuery.length >= 2 && (
        <div
          className="eos-combobox-options"
          id={listboxId}
          role="listbox"
          data-placement={dropdownPlacement}
          style={{ maxHeight: dropdownMaxHeight }}
        >
          {currentResult.state === 'loading' && (
            <span className="eos-combobox-message">Ищем товары…</span>
          )}
          {currentResult.state === 'error' && (
            <span className="eos-combobox-message">
              Не удалось загрузить товары
            </span>
          )}
          {currentResult.state === 'idle'
            && currentResult.items.length === 0 && (
            <span className="eos-combobox-message">Товары не найдены</span>
          )}
          {currentResult.items.map((product, index) => (
            <button
              type="button"
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={product.id === value}
              data-active={index === activeIndex}
              key={product.id}
              onPointerDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => selectProduct(product)}
            >
              <span>{product.name}</span>
              <small>{product.default_unit.short_name_ru}</small>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
