import { useEffect, useRef, useState } from 'react'
import { EosDateField, EosPagination, EosSelect } from '../../components/EosFormControls'
import { confirmRecipe, getRecipePortal, recipeError, recipeNorm, refreshRecipe, type RecipeChart, type RecipePortal, type RecipeApproval } from '../../services/productRecipes'
import './ProductRecipes.css'

const at = (value: string) => new Date(value).toLocaleString('ru-RU', { timeZone: 'Asia/Yekaterinburg' })
const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Yekaterinburg', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date())
function Approval({ value }: { value: RecipeApproval }) {
  return <div className="recipe-approval"><strong>Сверка исходной версии подтверждена</strong><p>{value.author || 'Сотрудник'} · {at(value.confirmed_at)}</p><p>{value.evidence}</p></div>
}
function Chart({ chart, charts, path = [] }: { chart: RecipeChart; charts: RecipeChart[]; path?: string[] }) {
  if (path.includes(chart.product_id) || path.length >= 50) return <p role="status">Вложенность требует проверки: цикл или превышение глубины. Рецептура заблокирована.</p>
  const nextPath = [...path, chart.product_id]
  return <article className="recipe-chart">
    <p><strong>{chart.name}</strong> · версия {chart.version_id.slice(0, 8)}</p>
    <p>Действует с {chart.valid_from || 'дата не подтверждена'} до {!chart.valid_to_known ? 'дата окончания не подтверждена' : chart.valid_to ? `${chart.valid_to} (не включая)` : 'дата окончания не задана'}</p>
    {chart.kind === 'SOURCE' && <p>Выход рецептуры: {recipeNorm(chart.base_amount)} {chart.unit || 'единица не подтверждена'}. Нормы приведены на этот выход.</p>}
    <p>{chart.writeoff_strategy} · {chart.size_strategy} · {chart.store_note}</p>
    <div className="product-table-wrap" role="region" aria-label={`Ингредиенты: ${chart.name}`} tabIndex={0}><table className="product-table recipe-table"><caption className="product-sr-only">{chart.kind === 'SOURCE' ? 'Исходные нормы' : 'Проекция списания'} · {chart.name}</caption><thead><tr><th scope="col">Ингредиент</th>{chart.kind === 'SOURCE' ? <><th scope="col">Брутто</th><th scope="col">Нетто</th><th scope="col">Выход</th></> : <th scope="col">Списание</th>}<th scope="col">Единица</th></tr></thead><tbody>{chart.items.map((row, index) => {
      const nested = charts.filter(c => c.kind === 'SOURCE' && c.roles.includes('TREE') && c.product_id === row.product_id)
      return <tr key={`${row.product_id}:${index}`}><td>{row.name}{row.scope_note && <small>{row.scope_note}</small>}{nested.length > 0 && <details><summary>Рецептура полуфабриката{nested.length > 1 ? ' · неоднозначные версии' : ''}</summary>{nested.map(c => <Chart key={c.version_id} chart={c} charts={charts} path={nextPath} />)}</details>}</td>{chart.kind === 'SOURCE' ? <><td>{recipeNorm(row.gross)}</td><td>{recipeNorm(row.net)}</td><td>{recipeNorm(row.output)}</td></> : <td>{recipeNorm(row.writeoff)}</td>}<td>{row.unit || 'Не подтверждена'}</td></tr>
    })}</tbody></table></div>
    {chart.items.length === 0 && <p role="status">Ингредиенты отсутствуют</p>}
    {chart.kind === 'SOURCE' && <details><summary>Технология приготовления</summary><p className="recipe-text">{chart.technology || 'Технологический текст отсутствует'}</p></details>}
  </article>
}
export function ProductRecipes({ productId }: { productId: string }) {
  const [context, setContext] = useState(''), [observationId, setObservationId] = useState(''), [offset, setOffset] = useState(0)
  const [date, setDate] = useState(today), [retry, setRetry] = useState(0)
  const [state, setState] = useState<{ key: string; selection: string; data: RecipePortal | null; error: string | null }>({ key: '', selection: '', data: null, error: null })
  const [busy, setBusy] = useState(false), [commandError, setCommandError] = useState(''), [evidence, setEvidence] = useState(''), [reviewed, setReviewed] = useState('')
  const commandLock = useRef(false), pendingRequest = useRef<{ signature: string; id: string } | null>(null)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const selection = JSON.stringify([productId, context, observationId, offset])
  const key = JSON.stringify([productId, context, observationId, offset, retry])
  useEffect(() => {
    const controller = new AbortController(), params = new URLSearchParams({ offset: String(offset), limit: '20' })
    if (context) params.set('context_key', context)
    if (observationId) params.set('observation_id', observationId)
    getRecipePortal(productId, params, controller.signal).then(data => { if (!controller.signal.aborted) setState({ key, selection, data, error: null }) }).catch(error => { if (!controller.signal.aborted) setState(previous => ({ key, selection, data: previous.selection === selection ? previous.data : null, error: recipeError(error) })) })
    return () => controller.abort()
  }, [key, selection, productId, context, observationId, offset])
  const data = state.selection === selection ? state.data : null, loading = state.key !== key
  useEffect(() => {
    if (!data?.refresh?.active || state.error) return
    const timer = setTimeout(() => setRetry(value => value + 1), 2500)
    return () => clearTimeout(timer)
  }, [data, state.error])
  const observation = data?.observation
  const disabled = busy || loading || Boolean(state.error) || Boolean(data?.refresh?.active)
  const changeSelection = (fn: () => void) => { setCommandError(''); setReviewed(''); setEvidence(''); fn() }
  async function update() {
    if (!data?.context_key || commandLock.current || disabled) return
    commandLock.current = true; setBusy(true); setCommandError('')
    const signature = JSON.stringify([productId, data.context_key, date])
    if (!pendingRequest.current || pendingRequest.current.signature !== signature) pendingRequest.current = { signature, id: crypto.randomUUID() }
    try {
      await refreshRecipe(productId, { context_key: data.context_key, effective_on: date, request_id: pendingRequest.current.id })
      pendingRequest.current = null
      if (mounted.current) { setObservationId(''); setReviewed(''); setEvidence(''); setRetry(value => value + 1) }
    } catch (error) { if (mounted.current) setCommandError(recipeError(error)) }
    finally { commandLock.current = false; if (mounted.current) setBusy(false) }
  }
  async function confirm() {
    if (!observation || commandLock.current || disabled || reviewed !== observation.id || evidence.trim().length < 10) return
    commandLock.current = true; setBusy(true); setCommandError('')
    try {
      await confirmRecipe(productId, { observation_id: observation.id, manifest_hash: observation.manifest_hash, office_evidence: evidence.trim() })
      if (mounted.current) { setReviewed(''); setEvidence(''); setRetry(value => value + 1) }
    } catch (error) { if (mounted.current) setCommandError(recipeError(error)) }
    finally { commandLock.current = false; if (mounted.current) setBusy(false) }
  }
  return <section className="product-knowledge-section product-recipes" aria-label="Технологическая карта"><h2>Технологическая карта</h2>
    <p className="product-notice">Нормы показаны для проверки. Готовность к производству не подтверждена. Сверка версии не снимает ограничения склада, размера и технологии.</p>
    {loading && <p role="status">Загружаем технологическую карту…</p>}
    {state.error && <div role="alert"><p>{state.error}</p><button className="secondary-action" onClick={() => setRetry(value => value + 1)}>Повторить загрузку</button></div>}
    {commandError && <p role="alert">{commandError}</p>}
    {data && <>
      <div className="recipe-controls"><label>Подразделение и контекст<EosSelect aria-label="Подразделение и контекст ТТК" value={context || data.context_key || ''} disabled={disabled} onChange={e => changeSelection(() => { setContext(e.target.value); setObservationId(''); setOffset(0) })}>{data.contexts.length === 0 && <option value="">Контекст не подтверждён</option>}{data.contexts.map(c => <option key={c.key} value={c.key}>{c.label} · {c.warehouse_label} · {c.size_label}</option>)}</EosSelect></label>
      {data.allowed_actions.includes('REFRESH') && <><EosDateField label="Дата рецептуры для обновления" value={date} disabled={disabled} onChange={e => setDate(e.target.value)} /><button className="secondary-action" disabled={disabled || !date} onClick={update}>{busy ? 'Выполняем действие…' : 'Обновить из iiko'}</button></>}</div>
      {data.refresh && <p role="status" aria-live="polite">{data.refresh.label}{data.refresh.finished_at && ` · ${at(data.refresh.finished_at)}`}</p>}
      {data.last_updated_at && <p>Последнее получение ТТК: {at(data.last_updated_at)}</p>}
      {!observation ? <p>Технологическая карта ещё не загружена.{data.contexts.length === 0 && ' Подтверждённый контекст источника пока отсутствует.'}</p> : <>
        <p className={`recipe-quality recipe-quality-${observation.status.toLowerCase()}`}><strong>{observation.status_label}</strong> · рецептура на {observation.effective_on} · получено {at(observation.observed_at)}{!observation.is_current && ' · Историческое наблюдение'}</p>
        {observation.issues.length > 0 && <ul>{[...new Set(observation.issues)].map(issue => <li key={issue}>{issue}</li>)}</ul>}
        {observation.confirmation && <Approval value={observation.confirmation} />}
        <h3>Исходная рецептура и вложенность</h3>
        {observation.charts.filter(c => c.kind === 'SOURCE' && c.roles.includes('ASSEMBLED') && c.product_id === observation.root_product_id).map(c => <Chart key={c.version_id} chart={c} charts={observation.charts} />)}
        {!observation.charts.some(c => c.roles.includes('ASSEMBLED')) && <p>Исходная рецептура отсутствует</p>}
        <details><summary>Проекция списания iiko</summary><p>Подготовленная проекция источника. Её нормы отличаются от брутто, нетто и выхода исходной рецептуры.</p>{observation.charts.filter(c => c.kind === 'PREPARED').map(c => <Chart key={c.version_id} chart={c} charts={[]} />)}</details>
        <details><summary>Версии из истории iiko</summary>{observation.charts.filter(c => c.kind === 'SOURCE' && c.roles.includes('HISTORY')).map(c => <Chart key={c.version_id} chart={c} charts={[]} />)}</details>
        {data.allowed_actions.includes('CONFIRM') && <div className="recipe-confirm"><h3>Подтвердить сверку исходной версии</h3><label><input type="checkbox" checked={reviewed === observation.id} disabled={disabled} onChange={e => setReviewed(e.target.checked ? observation.id : '')} /> Сверены нормы, единицы, выход, технология и вложенные версии с iikoOffice</label><label>Результат независимой сверки<textarea value={evidence} maxLength={1000} disabled={disabled} onChange={e => setEvidence(e.target.value)} placeholder="Дата и результат сверки с iikoOffice, ссылка на внутреннее свидетельство" /></label><button className="primary-action" disabled={disabled || reviewed !== observation.id || evidence.trim().length < 10} onClick={confirm}>Подтвердить версию</button></div>}
      </>}
      <h3>История обновлений и подтверждений</h3><ul className="recipe-history">{data.history.map(row => <li key={row.id}><button className="secondary-action" disabled={disabled} aria-current={row.id === observation?.id ? 'true' : undefined} onClick={() => changeSelection(() => setObservationId(row.id))}>{at(row.observed_at)} · на {row.effective_on} · {row.status_label}{row.is_current ? ' · последнее наблюдение' : ''}</button><small>Версия: {row.version_ids.map(id => id.slice(0, 8)).join(', ') || 'Не подтверждена'}</small>{row.confirmation && <Approval value={row.confirmation} />}</li>)}</ul>
      {observationId && <button className="secondary-action" disabled={disabled} onClick={() => changeSelection(() => setObservationId(''))}>К последнему наблюдению</button>}
      <EosPagination offset={data.offset} total={data.total} pageSize={data.limit} itemCount={data.history.length} onPageChange={next => changeSelection(() => setOffset(next))} />
    </>}
  </section>
}
