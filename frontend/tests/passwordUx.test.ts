import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import {
  copyGeneratedPassword,
  passwordInputType,
  passwordToggleLabel,
} from '../src/utils/passwordUx.ts'

test('password visibility starts hidden and toggles labels and input type', () => {
  assert.equal(passwordInputType(false), 'password')
  assert.equal(passwordToggleLabel(false), 'Показать пароль')
  assert.equal(passwordInputType(true), 'text')
  assert.equal(passwordToggleLabel(true), 'Скрыть пароль')
})

test('copy action writes only the generated password to clipboard', async () => {
  const copied: string[] = []
  await copyGeneratedPassword('generated-value', {
    writeText: async (value: string) => { copied.push(value) },
  })
  assert.deepEqual(copied, ['generated-value'])
})

test('HUMAN create, one-time credentials, reset and login toggle are wired in UI', () => {
  const employees = readFileSync(new URL('../src/pages/EmployeesPage.tsx', import.meta.url), 'utf8')
  const detail = readFileSync(new URL('../src/pages/EmployeeDetailPage.tsx', import.meta.url), 'utf8')
  const login = readFileSync(new URL('../src/pages/LoginPage.tsx', import.meta.url), 'utf8')
  const panel = readFileSync(new URL('../src/components/GeneratedCredentialsPanel.tsx', import.meta.url), 'utf8')
  assert.doesNotMatch(employees, /<span>Временный пароль<\/span><input/)
  assert.match(employees, /GeneratedCredentialsPanel/)
  assert.match(detail, /Сбросить пароль/)
  assert.match(detail, /resetEmployeePassword/)
  assert.match(panel, /Скопировать пароль/)
  assert.match(panel, /passwordToggleLabel/)
  assert.match(login, /aria-label=\{passwordToggleLabel\(passwordVisible\)\}/)
  assert.match(login, /passwordInputType\(passwordVisible\)/)
})
