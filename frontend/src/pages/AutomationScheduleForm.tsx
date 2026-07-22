import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import {
  createAutomationSchedule,
  updateAutomationSchedule,
  type AutomationSchedule,
  type AutomationScopeType,
  type AutomationType,
} from '../services/automation'
import {
  createSubmissionGuard,
  DEFAULT_SCHEDULE_FORM_VALUES,
  scheduleToFormValues,
  submitScheduleForm,
  type ScheduleFormErrors,
  type ScheduleFormValues,
} from './automationScheduleFormLogic'
import { automationTypeOptions } from './automationTypeCatalogLogic'

const WEEKDAYS = [
  { value: 0, label: 'Пн' },
  { value: 1, label: 'Вт' },
  { value: 2, label: 'Ср' },
  { value: 3, label: 'Чт' },
  { value: 4, label: 'Пт' },
  { value: 5, label: 'Сб' },
  { value: 6, label: 'Вс' },
]

const SCOPE_OPTIONS: Array<{
  value: AutomationScopeType
  label: string
}> = [
  { value: 'company', label: 'Вся компания' },
  { value: 'department', label: 'Подразделение' },
  { value: 'location', label: 'Объект' },
  { value: 'user', label: 'Пользователь' },
]

type AutomationScheduleFormProps = {
  schedule: AutomationSchedule | null
  automationTypes: AutomationType[]
  automationTypesLoading: boolean
  automationTypesError: string
  onCancel: () => void
  onSaved: (schedule: AutomationSchedule, isCreated: boolean) => void
}

function AutomationScheduleForm({
  schedule,
  automationTypes,
  automationTypesLoading,
  automationTypesError,
  onCancel,
  onSaved,
}: AutomationScheduleFormProps) {
  const initialValues = useMemo(
    () =>
      schedule
        ? scheduleToFormValues(schedule)
        : { ...DEFAULT_SCHEDULE_FORM_VALUES },
    [schedule],
  )
  const initialSnapshot = useMemo(
    () => JSON.stringify(initialValues),
    [initialValues],
  )
  const [values, setValues] = useState(initialValues)
  const [errors, setErrors] = useState<ScheduleFormErrors>({})
  const [submitError, setSubmitError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const guardRef = useRef(createSubmissionGuard())
  const nameInputRef = useRef<HTMLInputElement>(null)
  const isDirty = JSON.stringify(values) !== initialSnapshot
  const typeOptions = automationTypeOptions(
    automationTypes,
    schedule?.automation_type,
  )
  const availableTypeKeys = useMemo(
    () => new Set(automationTypes.map((item) => item.key)),
    [automationTypes],
  )
  const selectedType = automationTypes.find(
    (item) => item.key === values.automationType,
  )
  const catalogUnavailable =
    automationTypesLoading ||
    Boolean(automationTypesError) ||
    automationTypes.length === 0

  useEffect(() => {
    nameInputRef.current?.focus()
  }, [])

  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!isDirty || isSubmitting) {
        return
      }

      event.preventDefault()
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== 'Escape' || isSubmitting) {
        return
      }

      event.preventDefault()
      requestClose()
    }

    window.addEventListener('beforeunload', handleBeforeUnload)
    window.addEventListener('keydown', handleKeyDown)

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
      window.removeEventListener('keydown', handleKeyDown)
    }
  })

  function updateValue<Key extends keyof ScheduleFormValues>(
    key: Key,
    value: ScheduleFormValues[Key],
  ) {
    setValues((current) => ({ ...current, [key]: value }))
    setErrors((current) => ({ ...current, [key]: undefined }))
    setSubmitError('')
  }

  function requestClose() {
    if (
      isDirty &&
      !window.confirm('Закрыть форму? Несохранённые изменения будут потеряны.')
    ) {
      return
    }

    onCancel()
  }

  function toggleWeekday(weekday: number) {
    const weekdays = values.weekdays.includes(weekday)
      ? values.weekdays.filter((item) => item !== weekday)
      : [...values.weekdays, weekday]

    updateValue('weekdays', weekdays)
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (isSubmitting) {
      return
    }

    setErrors({})
    setSubmitError('')
    setIsSubmitting(true)

    const result = await submitScheduleForm(
      schedule
        ? { type: 'edit', scheduleId: schedule.id }
        : { type: 'create' },
      values,
      {
        create: createAutomationSchedule,
        update: updateAutomationSchedule,
      },
      guardRef.current,
      availableTypeKeys,
    )

    if (result.status === 'success') {
      onSaved(result.schedule, !schedule)
      return
    }

    if (result.status === 'validation') {
      setErrors(result.errors)
    } else if (result.status === 'error') {
      setSubmitError(result.message)
    } else if (result.status === 'busy') {
      return
    }

    setIsSubmitting(false)
  }

  const scopeLabel =
    SCOPE_OPTIONS.find((option) => option.value === values.scopeType)
      ?.label ?? 'области'

  return (
    <form
      className="automation-schedule-form"
      aria-labelledby="automation-form-title"
      noValidate
      onSubmit={(event) => void handleSubmit(event)}
    >
      <div className="automation-form-heading">
        <div>
          <p className="eyebrow">
            {schedule ? 'РЕДАКТИРОВАНИЕ' : 'НОВЫЙ РЕГЛАМЕНТ'}
          </p>
          <h2 id="automation-form-title">
            {schedule ? schedule.name : 'Настройка регламентной задачи'}
          </h2>
        </div>

        <button
          className="automation-form-close"
          type="button"
          aria-label="Закрыть форму"
          disabled={isSubmitting}
          onClick={requestClose}
        >
          ×
        </button>
      </div>

      <div className="automation-form-grid">
        <label className="automation-form-field automation-form-field-wide">
          <span>Название</span>
          <input
            ref={nameInputRef}
            value={values.name}
            maxLength={160}
            aria-invalid={Boolean(errors.name)}
            aria-describedby={errors.name ? 'schedule-name-error' : undefined}
            placeholder="Например, Ежедневный отчёт по продажам"
            onChange={(event) => updateValue('name', event.target.value)}
          />
          {errors.name && (
            <small id="schedule-name-error" className="automation-field-error">
              {errors.name}
            </small>
          )}
        </label>

        <label className="automation-form-field automation-form-field-wide">
          <span>Тип автоматизации</span>
          <select
            value={values.automationType}
            disabled={automationTypesLoading || Boolean(automationTypesError)}
            aria-invalid={Boolean(errors.automationType)}
            aria-describedby={
              errors.automationType ? 'automation-type-error' : undefined
            }
            onChange={(event) =>
              updateValue('automationType', event.target.value)
            }
          >
            <option value="">
              {automationTypesLoading
                ? 'Загружаем типы…'
                : 'Выберите тип автоматизации'}
            </option>
            {typeOptions.map((automationType) => (
              <option
                key={automationType.key}
                value={automationType.key}
                disabled={automationType.isLegacy}
              >
                {automationType.displayName}
              </option>
            ))}
          </select>
          {errors.automationType ? (
            <small
              id="automation-type-error"
              className="automation-field-error"
            >
              {errors.automationType}
            </small>
          ) : automationTypesError ? (
            <small className="automation-field-error">
              {automationTypesError}
            </small>
          ) : !automationTypesLoading && automationTypes.length === 0 ? (
            <small className="automation-field-error">
              Доступные типы автоматизаций не настроены
            </small>
          ) : selectedType ? (
            <small>{selectedType.description}</small>
          ) : (
            <small>Выберите поддерживаемый тип из каталога.</small>
          )}
        </label>

        <label className="automation-form-field">
          <span>Область действия</span>
          <select
            value={values.scopeType}
            onChange={(event) => {
              const scopeType = event.target.value as AutomationScopeType
              updateValue('scopeType', scopeType)

              if (scopeType === 'company') {
                updateValue('scopeId', '')
              }
            }}
          >
            {SCOPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        {values.scopeType !== 'company' && (
          <label className="automation-form-field">
            <span>Идентификатор: {scopeLabel.toLocaleLowerCase('ru')}</span>
            <input
              value={values.scopeId}
              maxLength={64}
              aria-invalid={Boolean(errors.scopeId)}
              aria-describedby={errors.scopeId ? 'scope-id-error' : undefined}
              placeholder="Например, department-1"
              onChange={(event) =>
                updateValue('scopeId', event.target.value)
              }
            />
            {errors.scopeId && (
              <small id="scope-id-error" className="automation-field-error">
                {errors.scopeId}
              </small>
            )}
          </label>
        )}

        <label className="automation-form-field">
          <span>Периодичность</span>
          <select
            value={values.scheduleType}
            onChange={(event) =>
              updateValue(
                'scheduleType',
                event.target.value as ScheduleFormValues['scheduleType'],
              )
            }
          >
            <option value="daily">Каждый день</option>
            <option value="weekly">В выбранные дни недели</option>
            <option value="interval">Через равные интервалы</option>
          </select>
        </label>

        {values.scheduleType === 'interval' ? (
          <label className="automation-form-field">
            <span>Повторять каждые, минут</span>
            <input
              type="number"
              min={1}
              max={10080}
              step={1}
              value={values.intervalMinutes}
              aria-invalid={Boolean(errors.intervalMinutes)}
              aria-describedby={
                errors.intervalMinutes ? 'interval-error' : undefined
              }
              onChange={(event) =>
                updateValue('intervalMinutes', event.target.value)
              }
            />
            {errors.intervalMinutes ? (
              <small id="interval-error" className="automation-field-error">
                {errors.intervalMinutes}
              </small>
            ) : (
              <small>От 1 минуты до 7 дней.</small>
            )}
          </label>
        ) : (
          <label className="automation-form-field">
            <span>Время запуска</span>
            <input
              type="time"
              value={values.time}
              aria-invalid={Boolean(errors.time)}
              aria-describedby={errors.time ? 'schedule-time-error' : undefined}
              onChange={(event) => updateValue('time', event.target.value)}
            />
            {errors.time && (
              <small
                id="schedule-time-error"
                className="automation-field-error"
              >
                {errors.time}
              </small>
            )}
          </label>
        )}

        {values.scheduleType === 'weekly' && (
          <fieldset className="automation-weekdays automation-form-field-wide">
            <legend>Дни недели</legend>
            <div>
              {WEEKDAYS.map((weekday) => (
                <label key={weekday.value}>
                  <input
                    type="checkbox"
                    checked={values.weekdays.includes(weekday.value)}
                    onChange={() => toggleWeekday(weekday.value)}
                  />
                  <span>{weekday.label}</span>
                </label>
              ))}
            </div>
            {errors.weekdays && (
              <small className="automation-field-error">
                {errors.weekdays}
              </small>
            )}
          </fieldset>
        )}

        <label className="automation-form-field">
          <span>Часовой пояс</span>
          <input
            value={values.timezone}
            maxLength={64}
            list="timezone-options"
            aria-invalid={Boolean(errors.timezone)}
            aria-describedby={errors.timezone ? 'timezone-error' : undefined}
            onChange={(event) => updateValue('timezone', event.target.value)}
          />
          <datalist id="timezone-options">
            <option value="Asia/Yekaterinburg" />
            <option value="Europe/Moscow" />
            <option value="UTC" />
          </datalist>
          {errors.timezone ? (
            <small id="timezone-error" className="automation-field-error">
              {errors.timezone}
            </small>
          ) : (
            <small>Используется для расчёта следующего запуска.</small>
          )}
        </label>

        <label className="automation-enabled-field">
          <input
            type="checkbox"
            checked={values.isEnabled}
            onChange={(event) =>
              updateValue('isEnabled', event.target.checked)
            }
          />
          <span>
            <strong>Активировать после сохранения</strong>
            <small>
              Следующий запуск рассчитает EnterpriseOS после сохранения.
            </small>
          </span>
        </label>
      </div>

      {submitError && (
        <p className="automation-form-error" role="alert">
          {submitError}
        </p>
      )}

      <div className="automation-form-actions">
        <button
          className="primary-action"
          type="submit"
          disabled={isSubmitting || catalogUnavailable}
        >
          {isSubmitting
            ? 'Сохраняем…'
            : schedule
              ? 'Сохранить изменения'
              : 'Создать регламент'}
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

export default AutomationScheduleForm
