import assert from 'node:assert/strict'
import test from 'node:test'
import type { AutomationScheduleAuditPage } from '../src/services/automation.ts'
import {
  auditEventDescription,
  auditEventLabel,
  loadScheduleAudit,
} from '../src/pages/automationScheduleAuditLogic.ts'

const PAGE: AutomationScheduleAuditPage = {
  items: [
    {
      id: 3,
      event_type: 'automation_schedule_updated',
      actor_user_id: 7,
      actor_display_name: 'Администратор',
      occurred_at: '2026-07-22T10:00:00Z',
      metadata: {
        changes: {
          name: { old: 'Отчёт', new: 'Сводка' },
          schedule_config: {
            old: { type: 'daily', time: '08:00' },
            new: { type: 'daily', time: '09:00' },
          },
        },
      },
    },
  ],
  total: 8,
  limit: 6,
  offset: 0,
}

test('успешно загружает журнал выбранного регламента', async () => {
  const result = await loadScheduleAudit(42, 1, 6, async (id, limit, offset) => {
    assert.deepEqual([id, limit, offset], [42, 6, 0])
    return PAGE
  })
  assert.deepEqual(result, { status: 'success', page: PAGE })
})

test('поддерживает пустое состояние и пагинацию', async () => {
  let receivedOffset = -1
  const result = await loadScheduleAudit(42, 3, 6, async (_id, _limit, offset) => {
    receivedOffset = offset
    return { ...PAGE, items: [], total: 0, offset }
  })
  assert.equal(receivedOffset, 12)
  assert.deepEqual(result.status === 'success' && result.page.items, [])
})

test('скрывает технический текст ошибки', async () => {
  const result = await loadScheduleAudit(42, 1, 6, async () => {
    throw new Error('postgresql://secret webhook payload')
  })
  assert.deepEqual(result, {
    status: 'error',
    message: 'Не удалось загрузить журнал действий. Попробуйте ещё раз',
  })
})

test('понятно отображает событие без raw JSON', () => {
  const event = PAGE.items[0]
  assert.ok(event)
  assert.equal(auditEventLabel(event.event_type), 'Регламент изменён')
  assert.equal(auditEventDescription(event), 'Изменены: название, расписание')
  assert.equal(auditEventDescription(event).includes('{'), false)
})
