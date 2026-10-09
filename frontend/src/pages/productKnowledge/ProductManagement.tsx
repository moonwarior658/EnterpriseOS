import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getIikoCandidates, getProductHistory, productCommand, type Catalog, type IikoCandidate, type Product, type ProductHistory } from '../../services/productKnowledge'

const contentFields = { description: 'Описание', characteristics: 'Характеристики', composition: 'Состав', allergens: 'Аллергены', storage: 'Хранение', training: 'Материалы для продавцов' } as const
const operations: Record<string, string> = { EDIT: 'Изменение карточки', STATUS: 'Изменение статуса', DELETE: 'Удаление из справочника', RESTORE: 'Восстановление', READD: 'Повторное добавление', ADD: 'Добавление', VERIFY: 'Проверка сведений' }
const fields: Record<string, string> = { name: 'Название', category_name: 'Категория', description: 'Описание', characteristics: 'Характеристики', composition: 'Состав', allergens: 'Аллергены', storage: 'Хранение', training: 'Материалы', sale_status: 'Статус', deleted_at: 'Удалено', verified_at: 'Проверено', verified_by_name: 'Проверил' }
const displayValue = (value: unknown) => value == null || value === '' ? 'Нет данных' : value === 'ON_SALE' ? 'В продаже' : value === 'OFF_SALE' ? 'Выведено из продажи' : String(value)
const errorText = (error: unknown) => error instanceof Error && error.name === 'ProductApiError' ? error.message : 'Не удалось сохранить изменения. Повторите позже'

export function ProductHistoryPanel({ product }: { product: Product }) {
  const [offset, setOffset] = useState(0)
  const [state, setState] = useState<{ key: string; rows: ProductHistory[]; error: boolean }>({key: '', rows: [], error: false})
  const key = `${product.id}:${product.version}:${offset}`
  useEffect(() => {
    const controller = new AbortController()
    getProductHistory(product.id, offset, controller.signal).then(rows => { if (!controller.signal.aborted) setState({key, rows, error: false}) }).catch(() => { if (!controller.signal.aborted) setState({key, rows: [], error: true}) })
    return () => controller.abort()
  }, [key, product.id, offset])
  return <section className="product-knowledge-section"><h2>История изменений EOS</h2>{state.key !== key ? <p role="status">Загружаем историю…</p> : state.error ? <p role="alert">Не удалось загрузить историю</p> : state.rows.length === 0 ? <p>Изменений пока нет</p> : state.rows.map(row => <article key={row.id}><p><strong>{operations[row.operation] || 'Изменение'}</strong> · {row.actor_name || 'Сотрудник'} · {new Date(row.occurred_at).toLocaleString('ru-RU', {timeZone: 'Asia/Yekaterinburg'})}</p><p>{row.reason}</p>{Object.entries(fields).filter(([field]) => row.before[field] !== row.after[field]).map(([field, label]) => <p key={field}>{label}: {displayValue(row.before[field])} → {displayValue(row.after[field])}</p>)}</article>)}<div className="product-management-actions"><button disabled={offset === 0} onClick={() => setOffset(x => Math.max(0, x - 25))}>Назад</button><button disabled={state.key !== key || state.rows.length < 25} onClick={() => setOffset(x => x + 25)}>Далее</button></div></section>
}

export function ProductEditor({ product, categories, onSaved }: { product: Product; categories: Catalog['categories']; onSaved: () => void }) {
  const [action, setAction] = useState('')
  const [reason, setReason] = useState('')
  const [status, setStatus] = useState(product.sale_status)
  const [draft, setDraft] = useState({ name: product.name, category_id: product.category_id || '', ...Object.fromEntries(Object.keys(contentFields).map(key => [key, product[key as keyof typeof contentFields] || ''])) })
  const [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const submitting = useRef(false)
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (submitting.current) return
    submitting.current = true; setBusy(true); setError('')
    const base = { expected_version: product.version, reason }
    const routes: Record<string, [string, string, object]> = {
      EDIT: ['/knowledge', 'PATCH', {...base, ...draft, category_id: draft.category_id || null}],
      STATUS: ['/sale-status', 'PATCH', {...base, sale_status: status}],
      DELETE: ['', 'DELETE', base], RESTORE: ['/restore', 'POST', base],
      VERIFY: ['/verification', 'PATCH', {...base, verified: !product.verified_at}],
    }
    try { const [path, method, body] = routes[action]; await productCommand(`/${product.id}${path}`, method, body); onSaved() }
    catch (error) { setError(errorText(error)) }
    finally { submitting.current = false; setBusy(false) }
  }
  if (!product.allowed_actions.length) return null
  return <section className="product-knowledge-section product-management"><h2>Управление продукцией</h2><div className="product-management-actions">{product.allowed_actions.map(code => <button className="secondary-action" key={code} disabled={busy} onClick={() => {setAction(code); setError('')}}>{code === 'VERIFY' ? product.verified_at ? 'Снять отметку «Проверено»' : 'Отметить «Проверено»' : operations[code]}</button>)}</div>{action && <form onSubmit={submit}><fieldset disabled={busy}>
    <legend>{action === 'VERIFY' ? 'Проверка сведений' : operations[action]}</legend>
    {action === 'EDIT' && <><label>Название для отображения<input required maxLength={500} value={draft.name} onChange={e => setDraft({...draft, name: e.target.value})} /></label><label>Категория EOS<select value={draft.category_id} onChange={e => setDraft({...draft, category_id: e.target.value})}><option value="">Без категории</option>{categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>{Object.entries(contentFields).map(([field, label]) => <label key={field}>{label}<textarea maxLength={10000} value={String(draft[field as keyof typeof draft] || '')} onChange={e => setDraft({...draft, [field]: e.target.value})} /></label>)}</>}
    {action === 'STATUS' && <label>Статус<select value={status} onChange={e => setStatus(e.target.value)}><option value="ON_SALE">В продаже</option><option value="OFF_SALE">Выведено из продажи</option></select></label>}
    {action === 'DELETE' && <p>Изделие исчезнет из рабочего каталога и будет недоступно для дальнейшего производственного планирования. История и связи сохранятся; изделие можно восстановить.</p>}
    {action === 'RESTORE' && <p>Изделие вернётся в каталог с сохранённым статусом продажи и сведениями.</p>}
    {action === 'EDIT' || action === 'STATUS' ? <p>После изменения отметка «Проверено» снимается.</p> : null}
    <label>Причина / комментарий<input required maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></label><div className="product-management-actions"><button type="submit" disabled={!reason.trim() || busy}>{busy ? 'Сохраняем…' : action === 'DELETE' ? 'Подтвердить удаление' : 'Сохранить'}</button><button type="button" onClick={() => setAction('')}>Отмена</button></div></fieldset></form>}{error && <p role="alert">{error} <button disabled={busy} onClick={onSaved}>Обновить карточку</button></p>}</section>
}

export function ManualProductAdd({ onSaved }: { onSaved: () => void }) {
  const navigate = useNavigate()
  const [query, setQuery] = useState(''), [rows, setRows] = useState<IikoCandidate[]>([]), [selected, setSelected] = useState<IikoCandidate | null>(null)
  const [status, setStatus] = useState('OFF_SALE'), [reason, setReason] = useState(''), [error, setError] = useState(''), [busy, setBusy] = useState(false)
  const [added, setAdded] = useState<Product | null>(null)
  const submitting = useRef(false), request = useRef<AbortController | null>(null)
  useEffect(() => () => request.current?.abort(), [])
  async function search(event: React.FormEvent) {
    event.preventDefault(); request.current?.abort(); const controller = new AbortController(); request.current = controller
    setBusy(true); setError(''); setRows([]); setSelected(null); setAdded(null)
    try { const rows = await getIikoCandidates(query, controller.signal); if (!controller.signal.aborted) setRows(rows) }
    catch(error) { if (!controller.signal.aborted) setError(errorText(error)) }
    finally { if (!controller.signal.aborted) setBusy(false) }
  }
  async function add(event: React.FormEvent) {
    event.preventDefault(); if (!selected || submitting.current) return
    submitting.current = true; setBusy(true); setError('')
    try { const product = await productCommand('', 'POST', {source_id: selected.source_id, iiko_product_id: selected.iiko_product_id, confirmation_hash: selected.confirmation_hash, sale_status: status, reason}); setAdded(product); setRows([]); setSelected(null); onSaved(); navigate(`/products/${product.id}`) }
    catch(error) { setError(errorText(error)) }
    finally { submitting.current = false; setBusy(false) }
  }
  return <details className="product-knowledge-section product-management"><summary>Добавить продукцию по UUID iiko</summary><form onSubmit={search}><label>Название или UUID iiko<input required value={query} maxLength={200} onChange={e => setQuery(e.target.value)} disabled={busy} /></label><button disabled={busy || !query.trim()}>{busy ? 'Проверяем…' : 'Найти в iiko'}</button></form><p>Выберите конкретную запись и подтвердите UUID. Уже добавленные изделия скрыты; удалённые можно добавить повторно.</p>{rows.map(row => <label key={row.iiko_product_id}><input type="radio" name="iiko-product" disabled={busy} checked={selected?.iiko_product_id === row.iiko_product_id} onChange={() => setSelected(row)} />{row.name} · {row.unit_name} · UUID: {row.iiko_product_id}{row.existing_id ? ' · восстановление' : ''}</label>)}{selected && <form onSubmit={add}><fieldset disabled={busy}><legend>Подтверждение выбранного изделия</legend><p>{selected.name} · UUID: {selected.iiko_product_id}</p>{selected.source_deleted && <p>Запись удалена в iiko; будет восстановлена только запись EOS.</p>}<label>Статус EOS<select value={status} onChange={e => setStatus(e.target.value)}><option value="OFF_SALE">Выведено из продажи</option><option value="ON_SALE">В продаже</option></select></label><label>Причина<input required maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></label><button disabled={busy || !reason.trim()}>Подтвердить UUID и {selected.existing_id ? 'восстановить' : 'добавить'}</button></fieldset></form>}{error && <p role="alert">{error}</p>}{added && <p role="status">Изделие добавлено: <Link to={`/products/${added.id}`}>{added.name}</Link></p>}</details>
}
