import type { WorkRequest } from '../services/requests'
import type { SupplyDashboardSummary } from '../services/supplyAdmin'

type AttentionAccess = {
  readRepairs: boolean
  readOperationalSupply: boolean
  readFinance: boolean
}

export type DashboardAttentionItem = { label: string; count: number; to: string }

export function buildAttentionItems(
  repairCount: number,
  summary: SupplyDashboardSummary | null,
  access: AttentionAccess,
): DashboardAttentionItem[] {
  const candidates: Array<DashboardAttentionItem & { visible: boolean }> = [
    { label: 'Ремонты без стоимости или документов', count: repairCount, to: '/requests/repair', visible: access.readRepairs },
    { label: 'Новые заявки на товары', count: summary?.new_requests ?? 0, to: '/supply/requests?status=SUBMITTED', visible: access.readOperationalSupply },
    { label: 'Заявки, требующие сопоставления', count: summary?.mapping_required ?? 0, to: '/supply/requests?has_needs_review=true', visible: access.readOperationalSupply },
    { label: 'Критические долги', count: summary?.critical_debts ?? 0, to: '/supply/debts?status=ACTIVE&severity=RED', visible: access.readFinance },
  ]
  return candidates.filter((item) => item.visible && item.count > 0)
    .map(({ label, count, to }) => ({ label, count, to }))
}

export function upcomingExternalVisits(
  requests: readonly WorkRequest[],
  now = Date.now(),
): WorkRequest[] {
  return requests.filter((item) => item.request_type === 'repair'
    && item.status === 'waiting_external'
    && item.visit_at !== null
    && Number.isFinite(Date.parse(item.visit_at))
    && Date.parse(item.visit_at) >= now)
    .sort((left, right) => Date.parse(left.visit_at!) - Date.parse(right.visit_at!))
    .slice(0, 3)
}
