import {
  useRef,
  useState,
  type FormEvent,
} from 'react'
import {
  createPublicRepairRequest,
  createPublicWarehouseRequest,
  type WorkRequestType,
} from '../services/requests'
import {
  createSubmissionGuard,
  DEPARTMENTS,
  EMPTY_WORK_REQUEST_FORM,
  PRIORITIES,
  REPAIR_CATEGORIES,
  submitPublicWorkRequest,
  validateRepairPhotos,
  WAREHOUSE_CATEGORIES,
  type WorkRequestFormErrors,
  type WorkRequestFormValues,
} from './workRequestLogic'

type WorkRequestFormPageProps = {
  requestType: WorkRequestType
}

function WorkRequestFormPage({
  requestType,
}: WorkRequestFormPageProps) {
  const isWarehouse = requestType === 'warehouse'
  const [values, setValues] = useState<WorkRequestFormValues>({
    ...EMPTY_WORK_REQUEST_FORM,
  })
  const [photos, setPhotos] = useState<File[]>([])
  const [errors, setErrors] = useState<WorkRequestFormErrors>({})
  const [message, setMessage] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const guardRef = useRef(createSubmissionGuard())
  const fileInputRef = useRef<HTMLInputElement>(null)

  function updateValue<Key extends keyof WorkRequestFormValues>(
    key: Key,
    value: WorkRequestFormValues[Key],
  ) {
    setValues((current) => ({ ...current, [key]: value }))
    setErrors((current) => ({ ...current, [key]: undefined }))
    setMessage('')
    setSubmitError('')
  }

  function updatePhotos(files: File[]) {
    setPhotos(files)
    setErrors((current) => ({
      ...current,
      photos: validateRepairPhotos(files) ?? undefined,
    }))
    setMessage('')
    setSubmitError('')
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isSubmitting) return

    setErrors({})
    setMessage('')
    setSubmitError('')
    setIsSubmitting(true)

    const result = await submitPublicWorkRequest(
      requestType,
      values,
      photos,
      createPublicWarehouseRequest,
      createPublicRepairRequest,
      guardRef.current,
    )

    if (result.status === 'success') {
      setValues({
        ...EMPTY_WORK_REQUEST_FORM,
      })
      setPhotos([])
      if (fileInputRef.current) fileInputRef.current.value = ''
      setMessage(
        isWarehouse
          ? 'Заявка на склад отправлена'
          : 'Заявка на ремонт отправлена',
      )
    } else if (result.status === 'validation') {
      setErrors(result.errors)
    } else if (result.status === 'error') {
      setSubmitError(result.message)
    }

    setIsSubmitting(false)
  }

  return (
    <main className="public-request-page">
      <section className="request-page">
        <div className="public-request-brand">
          <span className="brand-mark">EOS</span>
          <div>
            <p className="eyebrow">ENTERPRISEOS</p>
            <strong>Заявки подразделений</strong>
          </div>
        </div>

        <div className="request-panel">
          <div className="request-heading">
            <div>
              <p className="eyebrow">ПУБЛИЧНАЯ ФОРМА</p>
              <h1>
                {isWarehouse ? 'Заявка на склад' : 'Заявка на ремонт'}
              </h1>
              <p className="request-intro">
                Заполните форму — заявка сразу появится у администратора
                EnterpriseOS.
              </p>
            </div>
          </div>

          <form
            className="request-form"
            noValidate
            onSubmit={(event) => void handleSubmit(event)}
          >
            <label className="request-field">
              <span>Подразделение</span>
              <select
                value={values.department}
                aria-invalid={Boolean(errors.department)}
                disabled={isSubmitting}
                onChange={(event) =>
                  updateValue('department', event.target.value)
                }
              >
                <option value="">Выберите подразделение</option>
                {DEPARTMENTS.map((department) => (
                  <option key={department} value={department}>
                    {department}
                  </option>
                ))}
              </select>
              {errors.department && <small>{errors.department}</small>}
            </label>

            <label className="request-field">
              <span>Ваше имя</span>
              <input
                value={values.authorName}
                maxLength={128}
                aria-invalid={Boolean(errors.authorName)}
                disabled={isSubmitting}
                placeholder="Как к вам обращаться"
                onChange={(event) =>
                  updateValue('authorName', event.target.value)
                }
              />
              {errors.authorName && <small>{errors.authorName}</small>}
            </label>

            <label className="request-field">
              <span>
                {isWarehouse ? 'Категория склада' : 'Категория ремонта'}
              </span>
              <select
                value={values.category}
                aria-invalid={Boolean(errors.category)}
                disabled={isSubmitting}
                onChange={(event) =>
                  updateValue('category', event.target.value)
                }
              >
                <option value="">Выберите категорию</option>
                {isWarehouse
                  ? WAREHOUSE_CATEGORIES.map((category) => (
                      <option key={category.value} value={category.value}>
                        {category.label}
                      </option>
                    ))
                  : REPAIR_CATEGORIES.map((category) => (
                      <option key={category} value={category}>
                        {category}
                      </option>
                    ))}
              </select>
              {errors.category && <small>{errors.category}</small>}
            </label>

            {!isWarehouse && (
              <label className="request-field">
                <span>Приоритет</span>
                <select
                  value={values.priority}
                  aria-invalid={Boolean(errors.priority)}
                  disabled={isSubmitting}
                  onChange={(event) =>
                    updateValue('priority', event.target.value)
                  }
                >
                  <option value="">Выберите приоритет</option>
                  {PRIORITIES.map((priority) => (
                    <option key={priority.value} value={priority.value}>
                      {priority.label}
                    </option>
                  ))}
                </select>
                {errors.priority && <small>{errors.priority}</small>}
              </label>
            )}

            <label className="request-field request-field-wide">
              <span>
                {isWarehouse ? 'Содержание заявки' : 'Описание проблемы'}
              </span>
              <textarea
                value={values.description}
                maxLength={5000}
                rows={isWarehouse ? 8 : 6}
                aria-invalid={Boolean(errors.description)}
                disabled={isSubmitting}
                placeholder={
                  isWarehouse
                    ? 'Каждая позиция с новой строки.\n\nНапример:\nКартофель 10 кг\nМолоко 5 л\nКоробки 2 уп'
                    : 'Опишите, что сломалось, где находится оборудование и как проявляется проблема.'
                }
                onChange={(event) =>
                  updateValue('description', event.target.value)
                }
              />
              {errors.description && <small>{errors.description}</small>}
            </label>

            {!isWarehouse && (
              <label className="request-field request-field-wide">
                <span>Фотографии (до 5 файлов, не более 8 МБ каждый)</span>
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept="image/jpeg,image/png,image/webp"
                  disabled={isSubmitting}
                  aria-invalid={Boolean(errors.photos)}
                  onChange={(event) =>
                    updatePhotos(Array.from(event.target.files ?? []))
                  }
                />
                {photos.length > 0 && (
                  <ul className="request-file-list">
                    {photos.map((photo) => (
                      <li key={`${photo.name}-${photo.size}`}>
                        {photo.name}
                      </li>
                    ))}
                  </ul>
                )}
                {errors.photos && <small>{errors.photos}</small>}
              </label>
            )}

            {message && (
              <p className="request-message request-message-success">
                {message}
              </p>
            )}
            {submitError && (
              <p className="request-message request-message-error">
                {submitError}
              </p>
            )}

            <button
              className="primary-action request-submit"
              type="submit"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Отправляем…' : 'Отправить заявку'}
            </button>
          </form>
        </div>
      </section>
    </main>
  )
}

export default WorkRequestFormPage
