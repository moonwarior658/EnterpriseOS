import {
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type FormEvent,
  type KeyboardEvent,
} from 'react'
import { EosSelect } from '../components/EosFormControls'
import { createPublicRepairRequest } from '../services/requests'
import {
  addRepairPhotos,
  createSubmissionGuard,
  DEPARTMENTS,
  EMPTY_WORK_REQUEST_FORM,
  formatFileSize,
  PRIORITIES,
  REPAIR_CATEGORIES,
  submitPublicRepairRequest,
  type WorkRequestFormErrors,
  type WorkRequestFormValues,
} from './workRequestLogic'

type PhotoPreview = {
  file: File
  url: string
}

function WorkRequestFormPage() {
  const [values, setValues] = useState<WorkRequestFormValues>({
    ...EMPTY_WORK_REQUEST_FORM,
  })
  const [previews, setPreviews] = useState<PhotoPreview[]>([])
  const [errors, setErrors] = useState<WorkRequestFormErrors>({})
  const [message, setMessage] = useState('')
  const [submitError, setSubmitError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const guardRef = useRef(createSubmissionGuard())
  const fileInputRef = useRef<HTMLInputElement>(null)
  const objectUrlsRef = useRef(new Set<string>())

  useEffect(() => () => {
    objectUrlsRef.current.forEach((url) => URL.revokeObjectURL(url))
    objectUrlsRef.current.clear()
  }, [])

  function updateValue<Key extends keyof WorkRequestFormValues>(
    key: Key,
    value: WorkRequestFormValues[Key],
  ) {
    setValues((current) => ({ ...current, [key]: value }))
    setErrors((current) => ({ ...current, [key]: undefined }))
    setMessage('')
    setSubmitError('')
  }

  function openPicker() {
    if (!isSubmitting) fileInputRef.current?.click()
  }

  function addPhotos(files: File[]) {
    const result = addRepairPhotos(
      previews.map((preview) => preview.file),
      files,
    )
    const accepted = result.files.slice(previews.length)
    const nextPreviews = [...previews]
    let readingError = ''

    for (const file of accepted) {
      try {
        const url = URL.createObjectURL(file)
        objectUrlsRef.current.add(url)
        nextPreviews.push({ file, url })
      } catch {
        readingError = `Не удалось прочитать файл «${file.name}»`
      }
    }

    setPreviews(nextPreviews)
    setErrors((current) => ({
      ...current,
      photos: readingError || result.error || undefined,
    }))
    setMessage('')
    setSubmitError('')
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function removePhoto(index: number) {
    const preview = previews[index]
    URL.revokeObjectURL(preview.url)
    objectUrlsRef.current.delete(preview.url)
    setPreviews((current) => current.filter((_, itemIndex) => itemIndex !== index))
    setErrors((current) => ({ ...current, photos: undefined }))
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    addPhotos(Array.from(event.target.files ?? []))
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    if (isSubmitting) return
    setIsDragging(false)
    addPhotos(Array.from(event.dataTransfer.files))
  }

  function handleDropzoneKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      openPicker()
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isSubmitting) return

    setErrors({})
    setMessage('')
    setSubmitError('')
    setIsSubmitting(true)

    const result = await submitPublicRepairRequest(
      values,
      previews.map((preview) => preview.file),
      createPublicRepairRequest,
      guardRef.current,
    )

    if (result.status === 'success') {
      setValues({ ...EMPTY_WORK_REQUEST_FORM })
      previews.forEach((preview) => URL.revokeObjectURL(preview.url))
      objectUrlsRef.current.clear()
      setPreviews([])
      if (fileInputRef.current) fileInputRef.current.value = ''
      setMessage('Заявка на ремонт отправлена')
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
              <h1>Заявка на ремонт</h1>
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
              <EosSelect
                value={values.department}
                aria-invalid={Boolean(errors.department)}
                aria-required="true"
                disabled={isSubmitting}
                onChange={(event) => updateValue('department', event.target.value)}
              >
                <option value="">Выберите подразделение</option>
                {DEPARTMENTS.map((department) => (
                  <option key={department} value={department}>{department}</option>
                ))}
              </EosSelect>
              {errors.department && <small>{errors.department}</small>}
            </label>

            <label className="request-field">
              <span>Категория ремонта</span>
              <EosSelect
                value={values.category}
                aria-invalid={Boolean(errors.category)}
                aria-required="true"
                disabled={isSubmitting}
                onChange={(event) => updateValue('category', event.target.value)}
              >
                <option value="">Выберите категорию</option>
                {REPAIR_CATEGORIES.map((category) => (
                  <option key={category} value={category}>{category}</option>
                ))}
              </EosSelect>
              {errors.category && <small>{errors.category}</small>}
            </label>

            <label className="request-field">
              <span>Приоритет</span>
              <EosSelect
                value={values.priority}
                aria-invalid={Boolean(errors.priority)}
                aria-required="true"
                disabled={isSubmitting}
                onChange={(event) => updateValue('priority', event.target.value)}
              >
                <option value="">Выберите приоритет</option>
                {PRIORITIES.map((priority) => (
                  <option key={priority.value} value={priority.value}>
                    {priority.label}
                  </option>
                ))}
              </EosSelect>
              {errors.priority && <small>{errors.priority}</small>}
            </label>

            <label className="request-field request-field-wide">
              <span>Описание проблемы</span>
              <textarea
                value={values.description}
                maxLength={5000}
                rows={6}
                aria-invalid={Boolean(errors.description)}
                disabled={isSubmitting}
                placeholder="Опишите, что сломалось, где находится оборудование и как проявляется проблема."
                onChange={(event) => updateValue('description', event.target.value)}
              />
              {errors.description && <small>{errors.description}</small>}
            </label>

            <div className="request-field request-field-wide">
              <span>Фотографии</span>
              <div
                className={[
                  'repair-dropzone',
                  isDragging ? 'repair-dropzone-active' : '',
                  errors.photos ? 'repair-dropzone-error' : '',
                  isSubmitting ? 'repair-dropzone-disabled' : '',
                ].filter(Boolean).join(' ')}
                role="button"
                tabIndex={isSubmitting ? -1 : 0}
                aria-label="Выбрать фотографии ремонта"
                aria-disabled={isSubmitting}
                onClick={openPicker}
                onKeyDown={handleDropzoneKeyDown}
                onDragEnter={(event) => {
                  event.preventDefault()
                  if (!isSubmitting) setIsDragging(true)
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget as Node)) {
                    setIsDragging(false)
                  }
                }}
                onDrop={handleDrop}
              >
                <span className="repair-dropzone-icon" aria-hidden="true">▧</span>
                <strong>Перетащите фотографии сюда</strong>
                <span>или выберите файлы</span>
                <button
                  className="secondary-action"
                  type="button"
                  disabled={isSubmitting}
                  onClick={(event) => {
                    event.stopPropagation()
                    openPicker()
                  }}
                >
                  Выбрать файлы
                </button>
                <small>До 5 фотографий, не более 8 МБ каждая</small>
                <input
                  ref={fileInputRef}
                  className="visually-hidden"
                  type="file"
                  multiple
                  accept="image/jpeg,image/png,image/webp"
                  disabled={isSubmitting}
                  onChange={handleFileChange}
                />
              </div>
              {previews.length > 0 && (
                <div className="repair-photo-previews">
                  <p>Выбрано файлов: {previews.length}</p>
                  <ul>
                    {previews.map((preview, index) => (
                      <li key={preview.url}>
                        <img src={preview.url} alt="" />
                        <span>
                          <strong title={preview.file.name}>{preview.file.name}</strong>
                          <small>{formatFileSize(preview.file.size)}</small>
                        </span>
                        <button
                          type="button"
                          aria-label={`Удалить ${preview.file.name}`}
                          disabled={isSubmitting}
                          onClick={() => removePhoto(index)}
                        >
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {errors.photos && <small>{errors.photos}</small>}
            </div>

            {message && <p className="request-message request-message-success">{message}</p>}
            {submitError && <p className="request-message request-message-error">{submitError}</p>}

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
