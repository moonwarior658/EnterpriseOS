import { useEffect, useRef, useState } from 'react'
import SalesControlMenu from './SalesControlMenu'
import { downloadSalesExport } from '../services/salesAnalytics'

export default function SalesExportButtons({ endpoint, query }: { endpoint: string; query: (format: 'xlsx' | 'pdf') => string }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => { controller.current?.abort() }, [])
  async function download(format: 'xlsx' | 'pdf') {
    if (controller.current) return
    const request = new AbortController(); controller.current = request
    setBusy(true); setError('')
    try { await downloadSalesExport(endpoint, query(format), format, request.signal) }
    catch (e) { if (!request.signal.aborted) setError(e instanceof Error ? e.message : 'Не удалось сформировать экспорт') }
    finally { controller.current = null; if (!request.signal.aborted) setBusy(false) }
  }
  return <div className="statistics-export" aria-label="Экспорт статистики">
    <SalesControlMenu label={busy ? 'Формируем файл…' : 'Выгрузить'} disabled={busy} items={[
      { label: 'Excel', onSelect: () => { void download('xlsx') } },
      { label: 'PDF', onSelect: () => { void download('pdf') } },
    ]} />
    {busy && <span role="status">Формируем файл…</span>}{error && <span role="alert">{error}</span>}
  </div>
}
