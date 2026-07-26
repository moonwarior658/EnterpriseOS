import assert from 'node:assert/strict'
import test from 'node:test'
import type {
  CreateWorkRequestInput,
  WorkRequest,
} from '../src/services/requests.ts'
import {
  activeRequestsByType,
  createSubmissionGuard,
  priorityLabel,
  statusLabel,
  submitWorkRequest,
  warehouseCategoryLabel,
} from '../src/pages/workRequestLogic.ts'

const CREATED: WorkRequest = {
  id: 12,
  request_type: 'warehouse',
  department: 'Производство',
  description: 'Картофель 10 кг',
  status: 'new',
  warehouse_category: 'products',
  repair_category: null,
  priority: null,
  created_at: '2026-07-26T10:00:00Z',
  created_by_name: 'Сотрудник',
}

test('создаёт корректный payload складской заявки', async () => {
  let received: CreateWorkRequestInput | undefined

  const result = await submitWorkRequest(
    'warehouse',
    {
      department: 'Производство',
      category: 'products',
      priority: '',
      description: '  Картофель 10 кг  ',
    },
    async (input) => {
      received = input
      return CREATED
    },
    createSubmissionGuard(),
  )

  assert.equal(result.status, 'success')
  assert.deepEqual(received, {
    request_type: 'warehouse',
    department: 'Производство',
    description: 'Картофель 10 кг',
    warehouse_category: 'products',
  })
})

test('создаёт корректный payload ремонтной заявки', async () => {
  let received: CreateWorkRequestInput | undefined

  await submitWorkRequest(
    'repair',
    {
      department: 'Кафе',
      category: 'Кофемашина',
      priority: 'urgent',
      description: 'Не включается',
    },
    async (input) => {
      received = input
      return {
        ...CREATED,
        request_type: 'repair',
        warehouse_category: null,
        repair_category: 'Кофемашина',
        priority: 'urgent',
      }
    },
    createSubmissionGuard(),
  )

  assert.deepEqual(received, {
    request_type: 'repair',
    department: 'Кафе',
    description: 'Не включается',
    repair_category: 'Кофемашина',
    priority: 'urgent',
  })
})

test('валидирует обязательные поля до API', async () => {
  let calls = 0
  const result = await submitWorkRequest(
    'repair',
    {
      department: '',
      category: '',
      priority: '',
      description: '   ',
    },
    async () => {
      calls += 1
      return CREATED
    },
    createSubmissionGuard(),
  )

  assert.equal(result.status, 'validation')
  assert.equal(calls, 0)
  assert.deepEqual(
    result.status === 'validation' ? result.errors : {},
    {
      department: 'Выберите подразделение',
      category: 'Выберите категорию ремонта',
      priority: 'Выберите приоритет',
      description: 'Опишите проблему',
    },
  )
})

test('не допускает двойную отправку', async () => {
  let calls = 0
  let resolveRequest: ((request: WorkRequest) => void) | undefined
  const pending = new Promise<WorkRequest>((resolve) => {
    resolveRequest = resolve
  })
  const guard = createSubmissionGuard()
  const values = {
    department: 'М15',
    category: 'packaging',
    priority: '',
    description: 'Коробки 2 уп',
  }
  const create = async () => {
    calls += 1
    return pending
  }

  const first = submitWorkRequest('warehouse', values, create, guard)
  const second = await submitWorkRequest('warehouse', values, create, guard)

  assert.deepEqual(second, { status: 'busy' })
  assert.equal(calls, 1)
  assert.ok(resolveRequest)
  resolveRequest(CREATED)
  assert.equal((await first).status, 'success')
})

test('скрывает техническую backend-ошибку', async () => {
  const result = await submitWorkRequest(
    'warehouse',
    {
      department: 'М35',
      category: 'household',
      priority: '',
      description: 'Средство для уборки',
    },
    async () => {
      throw new Error('postgresql://secret stack trace')
    },
    createSubmissionGuard(),
  )

  assert.deepEqual(result, {
    status: 'error',
    message: 'Не удалось отправить заявку. Проверьте данные и попробуйте ещё раз',
  })
  assert.equal(JSON.stringify(result).includes('postgresql'), false)
})

test('Dashboard оставляет только активные заявки и русские подписи', () => {
  const completed = { ...CREATED, id: 13, status: 'completed' as const }
  const repair = {
    ...CREATED,
    id: 14,
    request_type: 'repair' as const,
    warehouse_category: null,
    repair_category: 'Интернет',
    priority: 'important' as const,
    status: 'in_progress' as const,
  }
  const active = activeRequestsByType([completed, repair, CREATED])

  assert.deepEqual(active.warehouse.map((item) => item.id), [12])
  assert.deepEqual(active.repair.map((item) => item.id), [14])
  assert.equal(statusLabel('in_progress'), 'В работе')
  assert.equal(warehouseCategoryLabel('household'), 'Хозяйственные товары')
  assert.equal(priorityLabel('urgent'), 'Срочно')
})
