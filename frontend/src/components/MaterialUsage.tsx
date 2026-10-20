import { useEffect, useState } from 'react'
import { materialRequest, type UsageMetric } from '../services/rawMaterials'

const categories:Record<string,string> = {PRODUCTION:'Списание при передаче готовой продукции',DIRECT_ISSUE:'Прямой отпуск сырья',TRANSFER:'Перемещения',RETURN:'Возвраты',INVENTORY:'Инвентаризации',WRITEOFF:'Прочие списания',COST_CORRECTION:'Корректировки стоимости',RECEIPT:'Приходы',OTHER:'Не классифицировано'}
export function UsageValue({metric}:{metric?:UsageMetric}) {
  if(!metric||metric.status==='NO_DATA') return <span>Нет данных</span>
  if(metric.status==='BLOCKED') return <span>Требуется проверка</span>
  return <span>{metric.quantity} {metric.unit}{metric.date_from&&<small>{metric.date_from} — {metric.date_to} (конец не включён)</small>}</span>
}
export function UsagePanel({id}:{id:string}) {
  const [items,setItems]=useState<UsageMetric[]>([]),[error,setError]=useState(''),[offset,setOffset]=useState(0)
  useEffect(()=>{const controller=new AbortController();materialRequest<{items:UsageMetric[]}>(`/${id}/usage?offset=${offset}`,{signal:controller.signal}).then(data=>{if(!Array.isArray(data.items))throw new Error('Invalid response');if(!controller.signal.aborted){setItems(data.items);setError('')}}).catch(()=>{if(!controller.signal.aborted)setError('Не удалось прочитать историю расхода')});return()=>controller.abort()},[id,offset])
  return <details><summary>История и расшифровка расхода</summary><p>Учётное списание ингредиента при передаче готовой продукции. Это не физический замер потребления партии. Норматив и отклонение не рассчитываются.</p>{error&&<p role="alert">{error}</p>}{!items.length&&<p>Нет данных</p>}{items.map((item,i)=><section key={item.id||i}><UsageValue metric={item}/>{item.reasons?.map(r=><p key={r}>Требуется проверка: {r}</p>)}<p>Количество в движениях: положительное — приход, отрицательное — расход.</p>{Object.entries(item.categories||{}).map(([k,v])=><p key={k}>{categories[k]||'Прочее'}: {v} {item.unit}</p>)}{item.balance&&<p>Баланс: {item.balance.opening??'Нет данных'} + {item.balance.signed_movements??'Нет данных'} = {item.balance.closing??'Нет данных'}; остаточная разница {item.balance.residual??'Не проверена'}</p>}<details><summary>Документы движения</summary>{item.documents?.map((d,j)=><p key={j}>{d.date} · №{d.number||'Не задан'} · {categories[d.category]||'Прочее'} · {d.quantity} {item.unit} · {d.document_id}</p>)}</details><p>Независимая сверка iikoOffice не выполнена.</p></section>)}{offset>0&&<button onClick={()=>setOffset(v=>Math.max(0,v-25))}>Предыдущие</button>}{items.length===25&&<button onClick={()=>setOffset(v=>v+25)}>Следующие</button>}</details>
}
