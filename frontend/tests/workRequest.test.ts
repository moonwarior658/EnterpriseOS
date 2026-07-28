import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  createPublicRepairRequest,
  getWorkRequests,
  type PublicRepairRequestInput,
  type WorkRequest,
} from '../src/services/requests.ts'
import {
  addRepairPhotos,
  activeRequestCountLabel,
  createSubmissionGuard,
  DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS,
  DEPARTMENTS,
  formatFileSize,
  priorityLabel,
  sortWorkRequests,
  statusLabel,
  submitPublicRepairRequest,
  validateRepairPhotos,
} from '../src/pages/workRequestLogic.ts'

const REPAIR: WorkRequest = {
  id: 12,
  request_type: 'repair',
  department: 'Бар ГХ',
  description: 'Не включается кофемашина',
  status: 'new',
  warehouse_category: null,
  repair_category: 'Кофемашина',
  priority: 'urgent',
  created_at: '2026-07-26T10:00:00Z',
  updated_at: '2026-07-26T10:00:00Z',
  created_by_name: 'Подразделение: Бар ГХ',
  attachment_count: 0,
  attachments: [],
}

test('формирует публичный payload ремонта и передаёт фотографии', async () => {
  let received: PublicRepairRequestInput | undefined
  let receivedPhotos: File[] = []
  const photo = new File(['photo'], 'machine.jpg', { type: 'image/jpeg' })

  const result = await submitPublicRepairRequest(
    {
      department: 'Бар ГХ',
      category: 'Кофемашина',
      priority: 'urgent',
      description: ' Не включается ',
    },
    [photo],
    async (input, photos) => {
      received = input
      receivedPhotos = photos
      return REPAIR
    },
    createSubmissionGuard(),
  )

  assert.equal(result.status, 'success')
  assert.deepEqual(received, {
    request_type: 'repair',
    department: 'Бар ГХ',
    description: 'Не включается',
    repair_category: 'Кофемашина',
    priority: 'urgent',
  })
  assert.deepEqual(receivedPhotos, [photo])
})

test('валидирует обязательные поля и защищает от двойной отправки', async () => {
  let calls = 0
  const invalid = await submitPublicRepairRequest(
    { department: '', category: '', priority: '', description: ' ' },
    [],
    async () => {
      calls += 1
      return REPAIR
    },
    createSubmissionGuard(),
  )
  assert.equal(invalid.status, 'validation')
  assert.equal(calls, 0)

  let resolveRequest: ((request: WorkRequest) => void) | undefined
  const pending = new Promise<WorkRequest>((resolve) => {
    resolveRequest = resolve
  })
  const guard = createSubmissionGuard()
  const values = {
    department: 'М35',
    category: 'Электрика',
    priority: 'important',
    description: 'Не работает свет',
  }
  const create = async () => {
    calls += 1
    return pending
  }
  const first = submitPublicRepairRequest(values, [], create, guard)
  const second = await submitPublicRepairRequest(values, [], create, guard)
  assert.deepEqual(second, { status: 'busy' })
  assert.ok(resolveRequest)
  resolveRequest(REPAIR)
  assert.equal((await first).status, 'success')
})

test('dropzone валидирует, объединяет и не дублирует фотографии', () => {
  const valid = new File(['photo'], 'ok.webp', {
    type: 'image/webp',
    lastModified: 10,
  })
  const duplicate = new File(['photo'], 'ok.webp', {
    type: 'image/webp',
    lastModified: 10,
  })
  const wrong = new File(['text'], 'note.txt', { type: 'text/plain' })
  const tooLarge = new File(
    [new Uint8Array(8 * 1024 * 1024 + 1)],
    'large.png',
    { type: 'image/png' },
  )

  assert.equal(validateRepairPhotos([valid]), null)
  assert.match(addRepairPhotos([valid], [duplicate]).error ?? '', /уже добавлен/)
  assert.match(addRepairPhotos([], [wrong]).error ?? '', /неподдерживаемый/)
  assert.match(addRepairPhotos([], [tooLarge]).error ?? '', /больше 8 МБ/)
  const six = Array.from({ length: 6 }, (_, index) => new File(
    ['x'],
    `${index}.jpg`,
    { type: 'image/jpeg', lastModified: index },
  ))
  const limited = addRepairPhotos([], six)
  assert.equal(limited.files.length, 5)
  assert.equal(limited.error, 'Можно прикрепить не более 5 фотографий')
  assert.equal(formatFileSize(1024), '1 КБ')
  assert.equal(formatFileSize(1024 * 1024), '1.0 МБ')
})

test('форма ремонта использует EOS Select и доступную dropzone', () => {
  const form = readFileSync(
    new URL('../src/pages/WorkRequestFormPage.tsx', import.meta.url),
    'utf8',
  )
  const detail = readFileSync(
    new URL('../src/pages/WorkRequestDetailPage.tsx', import.meta.url),
    'utf8',
  )
  assert.equal((form.match(/<EosSelect/g) ?? []).length, 3)
  assert.equal((detail.match(/<EosSelect/g) ?? []).length, 4)
  assert.match(form, /Перетащите фотографии сюда/)
  assert.match(form, /onDrop=\{handleDrop\}/)
  assert.match(form, /URL\.revokeObjectURL/)
  assert.match(form, /fileInputRef\.current\.value = ''/)
  assert.match(form, /repair-photo-previews/)
})

test('legacy warehouse UI удалён, а недельный redirect использует replace', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const layout = readFileSync(
    new URL('../src/layouts/AppLayout.tsx', import.meta.url),
    'utf8',
  )
  assert.match(
    app,
    /path="\/request\/warehouse"[\s\S]*?<Navigate to="\/request\/supply" replace \/>/,
  )
  assert.doesNotMatch(app, /path="\/public\/requests\/warehouse"/)
  assert.doesNotMatch(app, /path="\/requests\/warehouse"/)
  assert.doesNotMatch(layout, /Заявка на склад/)
  assert.match(app, /path="\/request\/repair"/)
  assert.match(app, /path="\/requests\/repair"/)
})

test('repair API сохраняет multipart upload-контракт', async () => {
  const originalFetch = globalThis.fetch
  let call: { url: string; options: RequestInit } | undefined
  globalThis.fetch = async (input, options = {}) => {
    call = { url: String(input), options }
    return new Response(JSON.stringify(REPAIR), {
      status: 201,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
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
  assert.equal(call?.url, '/api/public/requests')
  assert.ok(call?.options.body instanceof FormData)
  assert.equal((call?.options.body as FormData).getAll('photos').length, 1)
})

test('сохраняет общую repair/Dashboard логику и cache protection', async () => {
  assert.deepEqual(DEPARTMENTS, [
    'М15', 'М35', 'М6А', 'Цех ГХ', 'Бар ГХ', 'Кухня', 'Авто',
  ])
  assert.equal(activeRequestCountLabel(2), '2 активные заявки')
  assert.equal(statusLabel('in_progress'), 'В работе')
  assert.equal(priorityLabel('urgent'), 'Срочно')
  assert.equal(DASHBOARD_REQUESTS_REFRESH_INTERVAL_MS, 10_000)
  assert.equal(sortWorkRequests([REPAIR])[0].id, REPAIR.id)

  const originalFetch = globalThis.fetch
  const storageDescriptor = Object.getOwnPropertyDescriptor(
    globalThis,
    'sessionStorage',
  )
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: { getItem: () => 'test-token' },
  })
  let options: RequestInit | undefined
  globalThis.fetch = async (_input, requestOptions = {}) => {
    options = requestOptions
    return new Response('[]', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  }
  try {
    await getWorkRequests()
  } finally {
    globalThis.fetch = originalFetch
    if (storageDescriptor) {
      Object.defineProperty(globalThis, 'sessionStorage', storageDescriptor)
    } else {
      Reflect.deleteProperty(globalThis, 'sessionStorage')
    }
  }
  assert.equal(options?.cache, 'no-store')
})
