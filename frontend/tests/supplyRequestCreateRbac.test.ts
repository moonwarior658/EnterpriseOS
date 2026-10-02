import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('создание заявки находится в защищённом маршруте с проверкой смены Seller', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const list = readFileSync(new URL('../src/pages/SupplyRequestListPage.tsx', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/pages/SupplyRequestCreatePage.tsx', import.meta.url), 'utf8')
  const permissions = readFileSync(new URL('../src/services/useSupplyPermissions.ts', import.meta.url), 'utf8')
  assert.match(app, /path="\/supply\/requests\/new"[\s\S]*?ProtectedRoute allowedRoles=/)
  assert.match(list, /canCreateRequest && <Link/)
  assert.match(page, /context\?\.actual_department_id/)
  assert.match(page, /disabled=\{busy \|\| sellerOnly\}/)
  assert.match(permissions, /roles\.includes\('SELLER'\) && Boolean\(context\?\.shift_id\)/)
})

test('заявка отправляется с отдельными raw строками через авторизованный API', () => {
  const source = readFileSync(new URL('../src/services/actionContext.ts', import.meta.url), 'utf8')
  assert.match(source, /actionRequest\('\/supply\/requests'/)
  assert.match(source, /multiline_text[\s\S]*?split\('\\n'\)[\s\S]*?filter\(Boolean\)[\s\S]*?raw_text/)
})
