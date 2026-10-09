import { useEffect, useState } from 'react'
import { EosPagination, EosSelect } from '../../components/EosFormControls'
import { CostApiError, costLabel, exactCostNumber, getProductCosts, confirmProductCost, type CostReview, type CostPortal } from '../../services/productCosts'

const checkedAt = (value: string | undefined) => value ? new Date(value).toLocaleString('ru-RU', {timeZone: 'Asia/Yekaterinburg'}) : 'Нет данных'
export function ProductCosts({productId}: {productId: string}) {
  const [context, setContext] = useState(''), [offset, setOffset] = useState(0), [retry, setRetry] = useState(0)
  const [review, setReview] = useState(false)
  const key = JSON.stringify([productId, context, offset, retry, review])
  const [state, setState] = useState<{key: string; data: CostPortal | null; error: string | null}>({key:'',data:null,error:null})
  useEffect(() => {
    const controller = new AbortController()
    getProductCosts(productId,context,offset,controller.signal,review).then(data => {
      if (!controller.signal.aborted) setState({key,data,error:null})
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState({key,data:null,error:error instanceof CostApiError ? error.message : 'Не удалось загрузить себестоимость. Повторите позже'})
    })
    return () => controller.abort()
  }, [productId, context, offset, key, review])
  const loading = state.key !== key, data = state.data, current = data?.current
  return <section className="product-knowledge-section"><h2>Себестоимость · ССН</h2>
    {loading ? <p role="status">Загружаем себестоимость…</p> : state.error ? <div role="alert"><p>{state.error}</p><button className="secondary-action" onClick={() => setRetry(x => x+1)}>Повторить</button></div> : data && <>
      {data.contexts.length > 1 && <label>Контекст расчёта<EosSelect value={context || data.selected_context || ''} onChange={event => {setContext(event.target.value);setOffset(0)}}><option value="">Выберите контекст</option>{data.contexts.map(c => <option value={c.key} key={c.key}>{c.label} · {c.warehouse}</option>)}</EosSelect></label>}
      <p><strong>{costLabel(current)}</strong>{current?.status === 'VERIFIED' && ` / ${current.unit}`}</p>
      {data.note && <p role="status">{data.note}</p>}
      {current && <><p>{current.context} · {current.warehouse}</p><small>{current.source} · {current.method}<br />Стоимость на {checkedAt(current.stock_at)} · получено {checkedAt(current.observed_at)}</small></>}
      {current?.status === 'VERIFIED' && <>
        {current.verification_at && <p>Сверил: {current.verification_author || 'Ответственный сотрудник'} · {checkedAt(current.verification_at)}</p>}
        {current.estimated && <p role="status">* Оценочная ССН: содержит оценочную стоимость ингредиента, сверенную с iikoOffice.</p>}
        <details><summary>Расчёт по ингредиентам</summary><p>{current.rounding}</p><div className="product-table-wrap"><table className="product-table"><thead><tr><th>Ингредиент</th><th>Количество</th><th>Единица</th><th>Стоимость за единицу, ₽</th><th>Вклад в итог, ₽</th></tr></thead><tbody>{current.components.map((c,index) => <tr key={index}><td>{c.name || 'Наименование отсутствует'}</td><td>{exactCostNumber(c.quantity)}</td><td>{c.unit || 'Нет данных'}</td><td>{exactCostNumber(c.unit_cost)}</td><td>{exactCostNumber(c.contribution)}</td></tr>)}</tbody></table></div></details>
      </>}
      {data.can_review && current?.status !== 'VERIFIED' && <button className="secondary-action" onClick={() => setReview(value => !value)}>{review ? 'Закрыть проверку' : 'Проверить расчёт'}</button>}
      {review && data.review && <CostReviewForm key={`${productId}:${data.review.observation_id}`} productId={productId} review={data.review} onConfirmed={() => {setReview(false);setRetry(value => value+1)}} />}
      {data.history.length > 0 && <details><summary>История расчётов</summary>{data.history.map(row => <p key={row.observation_id}>{checkedAt(row.stock_at)}: {costLabel(row)} · {row.context} · исторический расчёт{row.verification_at && ` · сверил ${row.verification_author || 'Ответственный сотрудник'} ${checkedAt(row.verification_at)}`}</p>)}<EosPagination offset={offset} total={data.total} pageSize={25} itemCount={data.history.length} onPageChange={setOffset} /></details>}
    </>}
  </section>
}

function CostReviewForm({productId,review,onConfirmed}: {productId:string;review:CostReview;onConfirmed:()=>void}) {
  const [office,setOffice] = useState(''),[estimate,setEstimate] = useState(''),[evidence,setEvidence] = useState('')
  const [warehouse,setWarehouse] = useState(false),[context,setContext] = useState(false),[pending,setPending] = useState(false),[error,setError] = useState('')
  const normalized = office.trim().replace(',', '.')
  const valid = review.can_confirm && warehouse && context && estimate !== '' && /^\d+(\.\d{1,2})?$/.test(normalized) && evidence.trim().length >= 20
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();if (!valid || pending) return
    setPending(true);setError('')
    try {await confirmProductCost(productId,{observation_id:review.observation_id,content_hash:review.content_hash,office_ssn:normalized,estimated:estimate === 'yes',warehouse_confirmed:warehouse,context_confirmed:context,office_evidence:evidence.trim(),allow_updates:false});onConfirmed()}
    catch (failure:unknown) {setError(failure instanceof CostApiError ? failure.message : 'Не удалось сохранить подтверждение. Повторите сверку')}
    finally {setPending(false)}
  }
  return <section aria-label="Проверка расчёта"><h3>Проверка · Расчёт EOS по ТТК</h3>
    <p role="status">Неподтверждённый расчёт EOS. Используйте сумму только для сверки.</p>
    <p>{review.context} · {review.warehouse}</p>
    <p>Качество: {review.quality === 'EXCLUDED' ? 'Исключено из выпуска' : review.quality === 'REQUIRES_REVIEW' ? 'Требует сверки' : 'Недостаточно актуальных данных'}</p>
    <ul>{review.issues.map(issue => <li key={issue}>{issue}</li>)}</ul>
    <p>Кандидатная ССН: {review.candidate_amount === null ? 'Нет данных' : `${exactCostNumber(review.candidate_amount)} ₽`}</p>
    {review.components.length > 0 && <div className="product-table-wrap"><table className="product-table"><thead><tr><th>Ингредиент</th><th>Количество</th><th>Единица</th><th>Стоимость за единицу, ₽</th><th>Вклад в итог, ₽</th></tr></thead><tbody>{review.components.map((c,index) => <tr key={index}><td>{c.name || 'Нет наименования'}</td><td>{exactCostNumber(c.quantity)}</td><td>{c.unit || 'Нет данных'}</td><td>{exactCostNumber(c.unit_cost)}</td><td>{exactCostNumber(c.contribution)}</td></tr>)}</tbody></table></div>}
    {review.can_confirm && <form onSubmit={submit}><fieldset disabled={pending}><legend>Независимая сверка в iikoOffice</legend>
      <label>ССН из iikoOffice, ₽<input inputMode="decimal" value={office} onChange={event => setOffice(event.target.value)} required /></label>
      <label>Звёздочка возле ССН<EosSelect value={estimate} onChange={event => setEstimate(event.target.value)} required><option value="">Выберите после проверки</option><option value="no">Нет — неоценочная</option><option value="yes">Есть — оценочная</option></EosSelect></label>
      <label><input type="checkbox" checked={warehouse} onChange={event => setWarehouse(event.target.checked)} />Подтверждаю точный склад или полный набор складов расчёта</label>
      <label><input type="checkbox" checked={context} onChange={event => setContext(event.target.checked)} />Подтверждаю подразделение, дату и действующую ТТК</label>
      <label>Основание сверки<textarea value={evidence} onChange={event => setEvidence(event.target.value)} minLength={20} maxLength={1000} required /></label>
      <p>Подтверждение относится только к этому снимку. Расписание не включается.</p>
      <button className="primary-action" type="submit" disabled={!valid || pending}>{pending ? 'Сохраняем…' : 'Подтвердить этот расчёт'}</button>
    </fieldset>{error && <p role="alert">{error}</p>}</form>}
  </section>
}
