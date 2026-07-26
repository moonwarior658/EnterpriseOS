import assert from 'node:assert/strict'
import test from 'node:test'
import {
  createPublicRepairRequest,
  createPublicWarehouseRequest,
  type PublicRepairRequestInput,
  type PublicWarehouseRequestInput,
  type WorkRequest,
} from '../src/services/requests.ts'
import {
  activeRequestCountLabel,
  activeRequestsByType,
  createSubmissionGuard,
  DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS,
  DEPARTMENTS,
  priorityLabel,
  sortWorkRequests,
  statusLabel,
  submitPublicWorkRequest,
  validateRepairPhotos,
  warehouseCategoryLabel,
} from '../src/pages/workRequestLogic.ts'

const CREATED: WorkRequest = {
  id: 12,
  request_type: 'warehouse',
  department: 'М15',
  description: 'Картофель 10 кг',
  status: 'new',
  warehouse_category: 'products',
  repair_category: null,
  priority: null,
  created_at: '2026-07-26T10:00:00Z',
  updated_at: '2026-07-26T10:00:00Z',
  created_by_name: 'Подразделение: М15',
  attachment_count: 0,
  attachments: [],
}

test('формирует публичный payload складской заявки', async () => {
  let received: PublicWarehouseRequestInput | undefined
  const result = await submitPublicWorkRequest(
    'warehouse',
    {
      department: 'М15',
      category: 'products',
      priority: '',
      description: '  Картофель 10 кг  ',
    },
    [],
    async (input) => {
      received = input
      return CREATED
    },
    async () => CREATED,
    createSubmissionGuard(),
  )

  assert.equal(result.status, 'success')
  assert.deepEqual(received, {
    request_type: 'warehouse',
    department: 'М15',
    description: 'Картофель 10 кг',
    warehouse_category: 'products',
  })
})

test('формирует публичный payload ремонта и передаёт фотографии', async () => {
  let received: PublicRepairRequestInput | undefined
  let receivedPhotos: File[] = []
  const photo = new File(['photo'], 'machine.jpg', { type: 'image/jpeg' })

  await submitPublicWorkRequest(
    'repair',
    {
      department: 'Бар ГХ',
      category: 'Кофемашина',
      priority: 'urgent',
      description: 'Не включается',
    },
    [photo],
    async () => CREATED,
    async (input, photos) => {
      received = input
      receivedPhotos = photos
      return { ...CREATED, request_type: 'repair' }
    },
    createSubmissionGuard(),
  )

  assert.deepEqual(received, {
    request_type: 'repair',
    department: 'Бар ГХ',
    description: 'Не включается',
    repair_category: 'Кофемашина',
    priority: 'urgent',
  })
  assert.deepEqual(receivedPhotos, [photo])
})

test('валидирует обязательные поля публичной формы до API', async () => {
  let calls = 0
  const result = await submitPublicWorkRequest(
    'repair',
    {
      department: '',
      category: '',
      priority: '',
      description: '   ',
    },
    [],
    async () => {
      calls += 1
      return CREATED
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
    department: 'М35',
    category: 'packaging',
    priority: '',
    description: 'Коробки 2 уп',
  }
  const create = async () => {
    calls += 1
    return pending
  }

  const first = submitPublicWorkRequest(
    'warehouse', values, [], create, async () => CREATED, guard,
  )
  const second = await submitPublicWorkRequest(
    'warehouse', values, [], create, async () => CREATED, guard,
  )

  assert.deepEqual(second, { status: 'busy' })
  assert.equal(calls, 1)
  assert.ok(resolveRequest)
  resolveRequest(CREATED)
  assert.equal((await first).status, 'success')
})

test('использует только новый список подразделений', () => {
  assert.deepEqual(DEPARTMENTS, [
    'М15',
    'М35',
    'М6А',
    'Цех ГХ',
    'Бар ГХ',
    'Кухня',
    'Авто',
  ])
  assert.equal(DEPARTMENTS.includes('М6а' as never), false)
})

test('склоняет количество активных заявок', () => {
  assert.equal(activeRequestCountLabel(0), 'Нет активных заявок')
  assert.equal(activeRequestCountLabel(1), '1 активная заявка')
  assert.equal(activeRequestCountLabel(2), '2 активные заявки')
  assert.equal(activeRequestCountLabel(5), '5 активных заявок')
  assert.equal(activeRequestCountLabel(11), '11 активных заявок')
  assert.equal(activeRequestCountLabel(21), '21 активная заявка')
})

test('Dashboard обновляет заявки каждые 10 секунд', () => {
  assert.equal(DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS, 10_000)
})

test('сортирует активные заявки первыми и сохраняет порядок по дате', () => {
  const completed = {
    ...CREATED,
    id: 13,
    status: 'completed' as const,
    created_at: '2026-07-27T10:00:00Z',
  }
  const repair = {
    ...CREATED,
    id: 14,
    request_type: 'repair' as const,
    status: 'in_progress' as const,
    created_at: '2026-07-25T10:00:00Z',
  }
  assert.deepEqual(
    sortWorkRequests([completed, repair, CREATED]).map((item) => item.id),
    [12, 14, 13],
  )
  const active = activeRequestsByType([completed, repair, CREATED])
  assert.deepEqual(active.warehouse.map((item) => item.id), [12])
  assert.deepEqual(active.repair.map((item) => item.id), [14])
})

test('хранит русские подписи enum в общей логике', () => {
  assert.equal(statusLabel('new'), 'Новая')
  assert.equal(statusLabel('in_progress'), 'В работе')
  assert.equal(statusLabel('completed'), 'Выполнена')
  assert.equal(statusLabel('cancelled'), 'Отменена')
  assert.equal(warehouseCategoryLabel('household'), 'Хозяйственные товары')
  assert.equal(priorityLabel('urgent'), 'Срочно')
})

test('проверяет ограничения фотографий чистой функцией', () => {
  const valid = new File(['photo'], 'ok.webp', { type: 'image/webp' })
  const wrong = new File(['text'], 'note.txt', { type: 'text/plain' })
  const tooLarge = new File(
    [new Uint8Array(8 * 1024 * 1024 + 1)],
    'large.png',
    { type: 'image/png' },
  )
  assert.equal(validateRepairPhotos([valid]), null)
  assert.equal(
    validateRepairPhotos(Array.from({ length: 6 }, () => valid)),
    'Можно прикрепить не более 5 фотографий',
  )
  assert.equal(
    validateRepairPhotos([wrong]),
    'Допустимы только фотографии JPEG, PNG или WebP',
  )
  assert.equal(
    validateRepairPhotos([tooLarge]),
    'Размер одной фотографии не должен превышать 8 МБ',
  )
})

test('публичные API-функции используют JSON для склада и FormData для ремонта', async () => {
  const originalFetch = globalThis.fetch
  const calls: Array<{ url: string; options: RequestInit }> = []
  globalThis.fetch = async (input, options = {}) => {
    calls.push({ url: String(input), options })
    return new Response(JSON.stringify(CREATED), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    })
  }

  try {
    await createPublicWarehouseRequest({
      request_type: 'warehouse',
      department: 'Кухня',
      description: 'Молоко',
      warehouse_category: 'products',
    })
    await createPublicRepairRequest(
      {
        request_type: 'repair',
        department: 'Авто',
        description: 'Не заводится',
        repair_category: 'Другое',
        priority: 'important',
      },
      [new File(['photo'], 'auto.png', { type: 'image/png' })],
    )
  } finally {
    globalThis.fetch = originalFetch
  }

  assert.equal(calls[0].url, '/api/public/requests')
  assert.equal(calls[0].options.method, 'POST')
  assert.equal(typeof calls[0].options.body, 'string')
  assert.equal(
    JSON.parse(String(calls[0].options.body)).author_name,
    undefined,
  )
  assert.ok(calls[1].options.body instanceof FormData)
  const form = calls[1].options.body as FormData
  assert.equal(form.has('author_name'), false)
  assert.equal(form.getAll('photos').length, 1)
})
