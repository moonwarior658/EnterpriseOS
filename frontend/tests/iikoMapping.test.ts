import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  iikoMappingStatusLabel,
  iikoWarehouseRoleLabel,
  mappingActionLabel,
} from '../src/pages/iikoMappingLogic.ts'
import { mappingQuery } from '../src/services/iikoMapping.ts'


test('показывает безопасные русские статусы и роли mapping', () => {
  assert.equal(iikoMappingStatusLabel('SUGGESTED'), 'Предложено')
  assert.equal(iikoMappingStatusLabel('CONFLICT'), 'Конфликт')
  assert.equal(iikoWarehouseRoleLabel('FIXED_ASSETS'), 'Основные средства')
  assert.equal(mappingActionLabel('CONFIRMED'), 'Заменить связь')
})

test('формирует фильтры статуса, поиска, удалённых и конфликтов', () => {
  const query = mappingQuery({
    status: 'CONFLICT',
    search: '  молоко ',
    includeDeleted: true,
    conflictsOnly: true,
    limit: 100,
    offset: 200,
  })
  assert.equal(query.get('status'), 'CONFLICT')
  assert.equal(query.get('search'), 'молоко')
  assert.equal(query.get('include_deleted'), 'true')
  assert.equal(query.get('conflicts_only'), 'true')
  assert.equal(query.get('offset'), '200')
})

test('admin UI содержит три mapping-раздела и все явные действия', () => {
  const page = readFileSync(
    new URL('../src/pages/IikoMappingPage.tsx', import.meta.url),
    'utf8',
  )
  const app = readFileSync(new URL('../src/App.tsx', import.meta.url), 'utf8')
  assert.match(page, /Товары/)
  assert.match(page, /Единицы/)
  assert.match(page, /Склады/)
  assert.match(page, /Сформировать предложения/)
  assert.match(page, /Игнорировать/)
  assert.match(page, /Снять связь/)
  assert.match(page, /Показывать удалённые/)
  assert.match(page, /Только конфликты/)
  assert.match(app, /ProtectedRoute adminOnly><IikoMappingPage/)
})
