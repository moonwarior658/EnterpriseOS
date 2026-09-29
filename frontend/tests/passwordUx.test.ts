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
  const styles = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  const panel = readFileSync(new URL('../src/components/GeneratedCredentialsPanel.tsx', import.meta.url), 'utf8')
  assert.doesNotMatch(employees, /<span>Временный пароль<\/span><input/)
  assert.match(employees, /GeneratedCredentialsPanel/)
  assert.match(detail, /Сбросить пароль/)
  assert.match(detail, /resetEmployeePassword/)
  assert.match(panel, /Скопировать пароль/)
  assert.match(panel, /passwordToggleLabel/)
  assert.match(login, /aria-label=\{passwordToggleLabel\(passwordVisible\)\}/)
  assert.match(login, /passwordInputType\(passwordVisible\)/)
  assert.match(login, /aria-pressed=\{passwordVisible\}/)
  assert.match(login, /<svg viewBox="0 0 24 24" aria-hidden="true">/)
  assert.match(styles, /\.password-input-row \{[\s\S]*position: relative;/)
  assert.match(styles, /\.password-input-row input \{[\s\S]*padding-right: 3\.5rem;/)
  assert.match(styles, /\.login-form \.password-visibility-action \{[\s\S]*position: absolute;[\s\S]*right: 11px;[\s\S]*width: 32px;[\s\S]*height: 32px;/)
  assert.match(styles, /\.login-form \.password-visibility-action:hover \{[\s\S]*transform: translateY\(-50%\);/)
})
