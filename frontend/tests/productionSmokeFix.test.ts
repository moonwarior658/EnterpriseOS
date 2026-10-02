import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

test('dashboard uses cards without duplicate plain navigation block', () => {
  const dashboard = source('../src/pages/DashboardPage.tsx')
  assert.doesNotMatch(dashboard, /access\.links\.map/)
  assert.match(dashboard, /DashboardGrid widgets=/)
})

test('contractor directory is a catalog with inline multi select, pricing and repair history', () => {
  const page = source('../src/pages/RepairContractorsPage.tsx')
  assert.match(page, /\+ Добавить подрядчика/)
  assert.match(page, /contractor-catalog/)
  assert.match(page, /EosCheckbox/)
  assert.match(page, /Название специализации/)
  assert.match(page, /Прайс \/ условия/)
  assert.match(page, /Всего ремонтов/)
  assert.match(page, /Открыть ремонт|Ремонт №/)
  assert.doesNotMatch(page, /<h2>Специализации<\/h2>/)
})

test('employee card uses avatar upload and separates shift reads from admin iiko controls', () => {
  const page = source('../src/pages/EmployeeDetailPage.tsx')
  assert.doesNotMatch(page, /Ссылка на фото/)
  assert.match(page, /accept="image\/jpeg,image\/png,image\/webp"/)
  assert.match(page, /canReadShifts && <section/)
  assert.match(page, /isAdmin && <section[^]*Техническая связь iiko/)
  assert.match(page, /Обновлено:/)
})

test('employee onboarding makes HUMAN user creation primary and keeps linking secondary', () => {
  const page = source('../src/pages/EmployeeDetailPage.tsx')
  assert.match(page, /Создать доступ/)
  assert.match(page, /Привязать существующий User/)
  assert.match(page, /account_type: 'HUMAN'/)
  assert.match(page, /employee_id: employee\.id/)
  assert.match(page, /GeneratedCredentialsPanel/)
})
