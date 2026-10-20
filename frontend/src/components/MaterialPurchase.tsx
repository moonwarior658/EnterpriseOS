import { useEffect, useState } from 'react'
import { MaterialDocumentAdmissions } from './MaterialDocumentAdmissions'
import { materialRequest, type Material, type PurchaseMetric, type PurchaseHistory, type PurchaseSources, type PurchaseProgress } from '../services/rawMaterials'

const date = (value: string) => new Date(value).toLocaleString('ru-RU', {timeZone:'Asia/Yekaterinburg'})
const money = (value: string) => new Intl.NumberFormat('ru-RU',{maximumFractionDigits:4,minimumFractionDigits:2}).format(Number(value))
export function PurchaseValue({metric}: {metric?: PurchaseMetric}) {
  if (!metric || metric.status === 'NO_DATA') return <span>Нет данных</span>
  if (metric.status === 'BLOCKED') return <span>Требуется проверка</span>
  return <span>{metric.amount === null ? 'Нет данных' : `${money(metric.amount)} ₽/${metric.unit || 'ед.'} · с НДС`}{metric.receipt_at && <small>{date(metric.receipt_at)}</small>}{metric.stale && <small>Данные давно не обновлялись</small>}</span>
}

export function PurchasePanel({material,onUpdated}: {material:Material;onUpdated:()=>void}) {
  const [history,setHistory]=useState<PurchaseHistory|null>(null),[sources,setSources]=useState<PurchaseSources|null>(null)
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[offset,setOffset]=useState(0),[retry,setRetry]=useState(0)
  const [requestId,setRequestId]=useState<string|null>(null)
  const active=history?.refresh?.active || false
  useEffect(()=>{
    const controller=new AbortController()
    const load=()=>materialRequest<PurchaseHistory>(`/${material.id}/metrics?offset=${offset}`,{signal:controller.signal}).then(data=>{
      if(controller.signal.aborted)return
      setHistory(data)
      if(active&&!data.refresh?.active)onUpdated()
    }).catch(()=>{if(!controller.signal.aborted)setError('Не удалось проверить обновление. Сохранённая история доступна')})
    void load()
    const timer=active?setInterval(()=>{void load()},1500):null
    return()=>{controller.abort();if(timer)clearInterval(timer)}
  },[material.id,offset,retry,active,onUpdated])
  async function refresh() {
    setBusy(true);setError('')
    // Retry after an uncertain HTTP response preserves the same idempotency key.
    const id=requestId||crypto.randomUUID();setRequestId(id)
    try {
      const progress=await materialRequest<PurchaseProgress>(`/${material.id}/metrics/refresh`,{method:'POST',body:JSON.stringify({request_id:id})})
      setHistory(old=>({items:old?.items||[],refresh:progress}));setRequestId(null);setOffset(0);setRetry(v=>v+1)
    } catch {setError('Не удалось запустить обновление. Повторите позже; история сохранена')}
    finally {setBusy(false)}
  }
  async function source(id:string) {
    setError('');setSources(null)
    try {setSources(await materialRequest<PurchaseSources>(`/${material.id}/metrics/${id}/sources`))}
    catch {setError('Не удалось открыть документ-основание')}
  }
  const current=history?.current||(history?.items[0]&&offset===0?history.items[0]:material.last_purchase_price)
  return <div className="material-purchase"><p>Последняя цена прихода: <PurchaseValue metric={current}/></p>
    <p>Средневзвешенная за 6 полных месяцев: <PurchaseValue metric={current?.six_month_average||material.six_month_average}/></p>{(current?.six_month_average||material.six_month_average)?.date_from&&<small>{(current?.six_month_average||material.six_month_average)?.date_from} — {(current?.six_month_average||material.six_month_average)?.date_to} (конец не включён)</small>}
    {(current?.six_month_average||material.six_month_average)?.reasons?.map(reason=><p key={`average:${reason}`}>Средняя: {reason}</p>)}
    {current?.reasons?.map(reason=><p key={reason}>{reason}</p>)}
    {current?.date_from&&<small>Поиск приходов: {current.date_from} — {current.date_to} (конец не включён)</small>}
    {history?.refresh&&<p role="status">{history.refresh.label}</p>}
    {material.allowed_actions.includes('METRICS_REFRESH')&&<button disabled={busy||active} onClick={()=>void refresh()}>{busy||active?'Обновляем…':'Обновить показатели сырья'}</button>}
    {error&&<p role="alert">{error}</p>}
    <details><summary>История закупочной цены и документы</summary>
      {!history?.items.length?<p>Нет данных</p>:history.items.map(item=><div key={item.id}><PurchaseValue metric={item}/><p>Средняя: <PurchaseValue metric={item.six_month_average}/></p>{item.observed_at&&<small>Проверено {date(item.observed_at)}</small>}<button className="secondary-action" onClick={()=>void source(item.id!)}>Документ-основание</button></div>)}
      {offset>0&&<button onClick={()=>setOffset(v=>Math.max(0,v-25))}>Предыдущие</button>}{history?.items.length===25&&<button onClick={()=>setOffset(v=>v+25)}>Следующие</button>}
    </details>
    {sources&&<section aria-label="Документ-основание"><h3>Основание закупочной цены</h3><p>{sources.warehouse} · Суммы с НДС, RUB</p>
      {sources.admission_validity&&(!sources.admission_validity.latest||!sources.admission_validity.average)&&<p role="status">Исторический расчёт сохранён. Один из допусков отозван; текущие показатели требуют нового расчёта.</p>}
      {sources.documents&&<MaterialDocumentAdmissions material={material} sources={sources} onUpdated={()=>{setRetry(v=>v+1);onUpdated();void source(sources.metric.id!)}}/>}
      {sources.metric.status==='BLOCKED'&&<p>Суммы ниже — исходные данные для проверки, закупочная цена не подтверждена.</p>}
      {sources.analytics?.average&&<details><summary>Вычисление средней за шесть месяцев</summary><p>{sources.analytics.average.numerator} / {sources.analytics.average.denominator} {sources.metric.unit} · Сумма с НДС / количество</p>{sources.analytics.average.documents.map(d=><p key={d.document_id}>Накладная №{d.number} · {d.document_id}: {d.numerator} / {d.denominator}</p>)}</details>}
      {sources.candidates.map(doc=><div key={`${doc.document_id}:${doc.number}`}><h4>Накладная №{doc.number}</h4><p>{doc.receipt_at?date(doc.receipt_at):'Дата не подтверждена'} · {doc.supplier_name||'Поставщик требует проверки'}</p>
        <p>Документ: {doc.document_id}</p><p>Сумма / подтверждённое количество: {doc.numerator} / {doc.denominator}{sources.metric.status==='READY'?` ${sources.metric.unit}`:' (единицы требуют проверки)'}</p>
        <table><thead><tr><th>Строка</th><th>Количество</th><th>Сумма с НДС</th><th>В том числе НДС</th></tr></thead><tbody>{doc.lines.map((line,i)=><tr key={i}><td>{line.num??'Не задана'}</td><td>{line.actualAmount||'Не подтверждено'} {line.unit_name||'единица не подтверждена'}</td><td>{line.sum??'Нет данных'}</td><td>{line.vatSum??'Нет данных'}</td></tr>)}</tbody></table></div>)}
      {sources.unit_conflicts?.map(doc=><p key={doc.document_id}>Несовместимая единица: накладная №{doc.number}{doc.receipt_at?` · ${date(doc.receipt_at)}`:''}</p>)}
      {!!sources.exclusions.length&&<p>Исключено технических, внутренних или непроведённых документов: {sources.exclusions.length}</p>}
      <button className="secondary-action" onClick={()=>setSources(null)}>Закрыть расшифровку</button></section>}
  </div>
}
