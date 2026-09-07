import { useMemo, useRef, useState, type FormEvent } from 'react'
import {
  createSupplySupplier,
  updateSupplySupplier,
  type SupplySupplier,
} from '../services/supplyAdmin'
import {
  buildSupplierPayload,
  EMPTY_SUPPLIER_FORM,
  supplierErrorMessage,
  supplierToFormValues,
  type SupplySupplierFormValues,
} from './supplySupplierLogic'

type SupplySupplierFormProps = {
  supplier: SupplySupplier | null
  onCancel: () => void
  onSaved: (supplier: SupplySupplier, created: boolean) => void
}

type TextField = Exclude<keyof SupplySupplierFormValues, 'comment'>

type FieldDefinition = {
  key: TextField
  label: string
  maxLength: number
  type?: 'email' | 'tel'
  required?: boolean
}

const GROUPS: Array<{ title: string; fields: FieldDefinition[] }> = [
  {
    title: 'Основные данные',
    fields: [
      {
        key: 'displayName', label: 'Отображаемое название',
        maxLength: 240, required: true,
      },
      { key: 'legalName', label: 'Юридическое название', maxLength: 240 },
    ],
  },
  {
    title: 'Контакты',
    fields: [
      { key: 'phone', label: 'Телефон', maxLength: 40, type: 'tel' },
      {
        key: 'orderEmail', label: 'Email для заказов',
        maxLength: 320, type: 'email',
      },
    ],
  },
  {
    title: 'Реквизиты',
    fields: [
      { key: 'inn', label: 'ИНН', maxLength: 32 },
      { key: 'kpp', label: 'КПП', maxLength: 32 },
      { key: 'ogrn', label: 'ОГРН', maxLength: 32 },
      { key: 'legalAddress', label: 'Юридический адрес', maxLength: 1000 },
      { key: 'actualAddress', label: 'Фактический адрес', maxLength: 1000 },
    ],
  },
  {
    title: 'Банковские данные',
    fields: [
      { key: 'bankName', label: 'Банк', maxLength: 240 },
      { key: 'bik', label: 'БИК', maxLength: 32 },
      {
        key: 'correspondentAccount', label: 'Корреспондентский счёт',
        maxLength: 64,
      },
      {
        key: 'settlementAccount', label: 'Расчётный счёт', maxLength: 64,
      },
    ],
  },
]

function SupplySupplierForm({
  supplier,
  onCancel,
  onSaved,
}: SupplySupplierFormProps) {
  const initialValues = useMemo(
    () => supplier ? supplierToFormValues(supplier) : EMPTY_SUPPLIER_FORM,
    [supplier],
  )
  const initialSnapshot = useMemo(
    () => JSON.stringify(initialValues),
    [initialValues],
  )
  const [values, setValues] = useState(initialValues)
  const [displayNameError, setDisplayNameError] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submitGuard = useRef(false)
  const isDirty = JSON.stringify(values) !== initialSnapshot

  function updateValue(key: keyof SupplySupplierFormValues, value: string) {
    setValues((current) => ({ ...current, [key]: value }))
    if (key === 'displayName') setDisplayNameError('')
    setSubmitError('')
  }

  function requestClose() {
    if (
      isDirty
      && !window.confirm('Закрыть форму? Несохранённые изменения будут потеряны.')
    ) return
    onCancel()
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (submitGuard.current) return

    const result = buildSupplierPayload(values)
    if (result.status === 'validation') {
      setDisplayNameError(result.errors.displayName ?? '')
      return
    }

    submitGuard.current = true
    setIsSubmitting(true)
    setSubmitError('')
    try {
      const saved = supplier
        ? await updateSupplySupplier(supplier.id, result.payload)
        : await createSupplySupplier(result.payload)
      onSaved(saved, supplier === null)
    } catch (error) {
      setSubmitError(supplierErrorMessage(
        error,
        supplier
          ? 'Не удалось сохранить изменения поставщика'
          : 'Не удалось создать поставщика',
      ))
    } finally {
      submitGuard.current = false
      setIsSubmitting(false)
    }
  }

  return (
    <form className="supplier-form" onSubmit={handleSubmit}>
      <div className="supplier-form-heading">
        <div>
          <p className="eyebrow">
            {supplier ? 'КАРТОЧКА ПОСТАВЩИКА' : 'НОВЫЙ ПОСТАВЩИК'}
          </p>
          <h2>{supplier?.display_name ?? 'Добавить поставщика'}</h2>
        </div>
        <button
          className="secondary-action"
          type="button"
          disabled={isSubmitting}
          onClick={requestClose}
        >
          Закрыть
        </button>
      </div>

      {GROUPS.map((group) => (
        <fieldset className="supplier-form-section" key={group.title}>
          <legend>{group.title}</legend>
          <div className="supplier-form-grid">
            {group.fields.map((field) => (
              <label key={field.key}>
                <span>{field.label}</span>
                <input
                  type={field.type ?? 'text'}
                  value={values[field.key]}
                  maxLength={field.maxLength}
                  required={field.required}
                  aria-invalid={
                    field.key === 'displayName' && Boolean(displayNameError)
                  }
                  onChange={(event) => updateValue(field.key, event.target.value)}
                />
                {field.key === 'displayName' && displayNameError && (
                  <small>{displayNameError}</small>
                )}
              </label>
            ))}
          </div>
        </fieldset>
      ))}

      <fieldset className="supplier-form-section">
        <legend>Комментарий</legend>
        <label className="supplier-comment-field">
          <span>Внутренний комментарий</span>
          <textarea
            value={values.comment}
            maxLength={2000}
            rows={4}
            onChange={(event) => updateValue('comment', event.target.value)}
          />
        </label>
      </fieldset>

      {submitError && (
        <p className="request-message request-message-error" role="alert">
          {submitError}
        </p>
      )}

      <div className="supplier-form-actions">
        <button className="primary-action" type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Сохраняем…' : supplier ? 'Сохранить' : 'Создать'}
        </button>
        <button
          className="secondary-action"
          type="button"
          disabled={isSubmitting}
          onClick={requestClose}
        >
          Отмена
        </button>
      </div>
    </form>
  )
}

export default SupplySupplierForm
