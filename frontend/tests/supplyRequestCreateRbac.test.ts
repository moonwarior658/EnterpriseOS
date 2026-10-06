import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

test('канонический create route использует существующий request window flow', () => {
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  const list = readFileSync(new URL('../src/pages/SupplyRequestListPage.tsx', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/pages/SupplyRequestCreatePage.tsx', import.meta.url), 'utf8')
  const flow = readFileSync(new URL('../src/pages/SellerSupplyRequestPage.tsx', import.meta.url), 'utf8')
  assert.match(app, /path="\/supply\/requests\/new"[\s\S]*?ProtectedRoute allowedRoles=/)
  assert.match(page, /export \{ default \} from '\.\/SellerSupplyRequestPage'/)
  assert.match(list, /createContext\?\.allowed_actions\.includes\('CREATE'\)/)
  assert.doesNotMatch(page + flow, /EosDateField|Цикл заявок|Дата потребности|<span>Направление<\/span>/)
  assert.doesNotMatch(list, /roles\.includes\('SELLER'\)/)
})

test('save/confirm продолжают использовать существующий авторизованный API', () => {
  const source = readFileSync(new URL('../src/services/actionContext.ts', import.meta.url), 'utf8')
  const flow = readFileSync(new URL('../src/pages/SellerSupplyRequestPage.tsx', import.meta.url), 'utf8')
  assert.match(source, /actionRequest\('\/supply\/seller\/request'/)
  assert.match(source, /actionRequest\('\/supply\/seller\/request\/confirm'/)
  assert.match(flow, /expected_version: windowInfo\.request\?\.version/)
  assert.match(flow, /disabled=\{busy \|\| Boolean\(windowInfo\.request\)\}/)
})
