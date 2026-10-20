import { useEffect, useRef, useState } from 'react'
import { MaterialDocumentAdmissions } from './MaterialDocumentAdmissions'
import { MaterialDialog } from './MaterialDialog'
import { UsagePanel, UsageValue } from './MaterialUsage'
import { materialNumber, materialPeriod } from './materialPresentation'
import { materialRequest, type Material, type PurchaseMetric, type PurchaseHistory, type PurchaseSources, type PurchaseProgress } from '../services/rawMaterials'

const date = (value: string) => new Date(value).toLocaleString('ru-RU', {timeZone:'Asia/Yekaterinburg'})
export function PurchaseValue({metric}: {metric?: PurchaseMetric}) {
  if (!metric || metric.status === 'NO_DATA' || (metric.status==='READY'&&metric.amount===null)) return <span className="material-status material-status-empty">Нет данных</span>
  if (metric.status === 'BLOCKED') return <span className="material-status material-status-blocked">Требуется проверка</span>
  return <span className="material-metric-value">{materialNumber(metric.amount)} ₽/{metric.unit || 'ед.'}</span>
}

export function PurchasePanel({material,onUpdated}: {material:Material;onUpdated:()=>void}) {
  const [history,setHistory]=useState<PurchaseHistory|null>(null),[sources,setSources]=useState<PurchaseSources|null>(null)
  const [error,setError]=useState(''),[busy,setBusy]=useState(false),[offset,setOffset]=useState(0),[retry,setRetry]=useState(0)
  const [open,setOpen]=useState(false),[sourceBusy,setSourceBusy]=useState(false),[dirty,setDirty]=useState(false),[decisionBusy,setDecisionBusy]=useState(false)
  const [requestId,setRequestId]=useState<string|null>(null)
  const pending=useRef(false),sourceRequest=useRef(0),updated=useRef(onUpdated)
  useEffect(()=>{updated.current=onUpdated},[onUpdated])
  const active=history?.refresh?.active || false
  useEffect(()=>{
    if(!material.purchase_access)return
    const controller=new AbortController()
    const load=()=>materialRequest<PurchaseHistory>(`/${material.id}/metrics?offset=${offset}`,{signal:controller.signal}).then(data=>{
      if(controller.signal.aborted)return
      setHistory(data)
      if(active&&!data.refresh?.active)updated.current()
    }).catch(()=>{if(!controller.signal.aborted)setError('Не удалось проверить обновление. Сохранённая история доступна')})
    void load()
    const timer=active?setInterval(()=>{void load()},1500):null
    return()=>{controller.abort();if(timer)clearInterval(timer)}
  },[material.id,material.purchase_access,offset,retry,active])
  async function refresh() {
    if(pending.current)return
    pending.current=true;setBusy(true);setError('')
    // Preserve the key after an uncertain response; EOS remains the authority.
    const id=requestId||crypto.randomUUID();setRequestId(id)
    try {
      const progress=await materialRequest<PurchaseProgress>(`/${material.id}/metrics/refresh`,{method:'POST',body:JSON.stringify({request_id:id})})
      setHistory(old=>({items:old?.items||[],refresh:progress}));setRequestId(null);setOffset(0);setRetry(v=>v+1)
    } catch {setError('Не удалось запустить обновление. Повторите позже; история сохранена')}
    finally {pending.current=false;setBusy(false)}
  }
  async function source(id:string) {
    const serial=++sourceRequest.current
    setError('');setSourceBusy(true)
    try {const data=await materialRequest<PurchaseSources>(`/${material.id}/metrics/${id}/sources`);if(serial===sourceRequest.current)setSources(data)}
    catch {if(serial===sourceRequest.current)setError('Не удалось открыть документ-основание')}
    finally {if(serial===sourceRequest.current)setSourceBusy(false)}
  }
  const current=history?.current||(history?.items[0]&&offset===0?history.items[0]:material.last_purchase_price)
  const average=current?.six_month_average||material.six_month_average
  return <section className="product-knowledge-section material-purchase">
    <div className="material-section-heading"><h2>Закупочные показатели</h2>{material.allowed_actions.includes('METRICS_REFRESH')&&<button className="secondary-action" disabled={busy||active} onClick={()=>void refresh()}>{busy||active?'Обновляем…':'Обновить показатели'}</button>}</div>
    <div className="material-metrics">
      <article><h3>Последняя цена прихода</h3>{material.purchase_access?<><PurchaseValue metric={current}/><small>С НДС{current?.receipt_at?` · ${date(current.receipt_at)}`:''}</small>{current?.stale&&<small>Данные давно не обновлялись</small>}</>:<p>Нет доступа к закупочным ценам</p>}</article>
      <article><h3>Средневзвешенная цена</h3>{material.purchase_access?<><PurchaseValue metric={average}/><small>С НДС · 6 полных календарных месяцев</small><small>{materialPeriod(average?.date_from,average?.date_to)}</small></>:<p>Нет доступа к закупочным ценам</p>}</article>
      <article><h3>Расход за прошлый месяц</h3><UsageValue metric={material.monthly_consumption}/><small>{materialPeriod(material.monthly_consumption?.date_from,material.monthly_consumption?.date_to)}</small></article>
    </div>
    {history?.refresh&&<p role="status">{history.refresh.label}</p>}
    {error&&<p role="alert">{error}</p>}
    <button className="secondary-action" onClick={()=>setOpen(true)}>{material.purchase_access?'История показателей и документы':'История расхода'}</button>
    {open&&<MaterialDialog title="История показателей и документы" dirty={dirty} busy={decisionBusy} onClose={()=>{setOpen(false);setSources(null);sourceRequest.current++}}>
      {material.purchase_access&&<>
        <p>Цены с НДС. Учётная единица: {material.unit||'Не подтверждена'}. Ошибка обновления не удаляет сохранённую историю.</p>
        <p><strong>Расчётный период средней:</strong> {materialPeriod(average?.date_from,average?.date_to)}</p>
        <p><strong>Период поиска последних приходов:</strong> {materialPeriod(current?.date_from,current?.date_to)}</p>
        {average?.reasons?.map(reason=><p key={`average:${reason}`} className="material-notice">Средняя: {reason}</p>)}
        {current?.reasons?.map(reason=><p key={reason} className="material-notice">Последняя цена: {reason}</p>)}
        {error&&<p role="alert">{error}</p>}
        <h3>Сохранённые расчёты</h3>
        {history===null?<p role="status">Загружаем историю…</p>:!history.items.length?<p>Нет данных</p>:history.items.map(item=><article className="material-history-item" key={item.id}>
          <p><strong>Последняя цена:</strong> <PurchaseValue metric={item}/></p><p><strong>Средняя:</strong> <PurchaseValue metric={item.six_month_average}/></p>
          {item.receipt_at&&<p>Последний приход: {date(item.receipt_at)}</p>}{item.observed_at&&<p>Проверено: {date(item.observed_at)}</p>}
          <button className="secondary-action" disabled={sourceBusy||dirty||decisionBusy} onClick={()=>void source(item.id!)}>Документ-основание</button>
        </article>)}
        <div className="product-actions">{offset>0&&<button className="secondary-action" disabled={dirty||sourceBusy} onClick={()=>setOffset(v=>Math.max(0,v-25))}>Предыдущие</button>}{history?.items.length===25&&<button className="secondary-action" disabled={dirty||sourceBusy} onClick={()=>setOffset(v=>v+25)}>Следующие</button>}</div>
        {sourceBusy&&<p role="status">Загружаем документы…</p>}
        {sources&&<section aria-label="Документ-основание" className="material-source"><h3>Основание закупочной цены</h3><p>{sources.warehouse} · Суммы с НДС, RUB</p>
          {sources.admission_validity&&(!sources.admission_validity.latest||!sources.admission_validity.average)&&<p role="status">Исторический расчёт сохранён. Один из допусков отозван; текущие показатели требуют нового расчёта.</p>}
          {sources.documents&&<MaterialDocumentAdmissions key={`${sources.metric.id}:${sources.hash}`} material={material} sources={sources} onDirtyChange={setDirty} onBusyChange={setDecisionBusy} onUpdated={()=>{setRetry(v=>v+1);onUpdated();void source(sources.metric.id!)}}/>}
          {sources.metric.status==='BLOCKED'&&<p>Суммы ниже — исходные данные для проверки, закупочная цена не подтверждена.</p>}
          {sources.analytics?.average&&<section><h4>Вычисление средней за шесть месяцев</h4><p>Сумма с НДС / подтверждённое количество: {materialNumber(sources.analytics.average.numerator)} ₽ / {materialNumber(sources.analytics.average.denominator)} {sources.metric.unit}</p>{sources.analytics.average.documents.map(d=><p key={d.document_id}>Накладная №{d.number}: {materialNumber(d.numerator)} ₽ / {materialNumber(d.denominator)} {sources.metric.unit}</p>)}</section>}
          {sources.candidates.map(doc=><article className="material-history-item" key={`${doc.document_id}:${doc.number}`}><h4>Накладная №{doc.number}</h4><p>{doc.receipt_at?date(doc.receipt_at):'Дата не подтверждена'} · {doc.supplier_name||'Поставщик требует проверки'}</p>
            <p>Документ: {doc.document_id}</p><p>Сумма / подтверждённое количество: {materialNumber(doc.numerator)} ₽ / {materialNumber(doc.denominator)}{sources.metric.status==='READY'?` ${sources.metric.unit}`:' (единицы требуют проверки)'}</p>
            <div className="material-document-table"><table className="product-table"><thead><tr><th>Строка</th><th>Количество</th><th>Сумма с НДС</th><th>В том числе НДС</th></tr></thead><tbody>{doc.lines.map((line,i)=><tr key={i}><td>{line.num??'Не задана'}</td><td>{materialNumber(line.actualAmount)} {line.unit_name||'единица не подтверждена'}</td><td>{materialNumber(line.sum)} ₽</td><td>{materialNumber(line.vatSum)} ₽</td></tr>)}</tbody></table></div></article>)}
          {sources.unit_conflicts?.map(doc=><p key={doc.document_id}>Несовместимая единица: накладная №{doc.number}{doc.receipt_at?` · ${date(doc.receipt_at)}`:''}</p>)}
          {!!sources.exclusions.length&&<p>Исключено технических, внутренних или непроведённых документов: {sources.exclusions.length}</p>}
          <button className="secondary-action" disabled={dirty||decisionBusy} onClick={()=>setSources(null)}>Закрыть расшифровку</button>
        </section>}
      </>}
      <UsagePanel key={material.id} id={material.id}/>
    </MaterialDialog>}
  </section>
}
