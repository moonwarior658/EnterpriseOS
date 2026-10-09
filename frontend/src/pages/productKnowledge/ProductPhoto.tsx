import { useEffect, useRef, useState } from 'react'
import { getStoredToken } from '../../services/auth'
import { ProductApiError, productCommand, type Product } from '../../services/productKnowledge'

export function ProductPhoto({ product, large = false }: { product: Product; large?: boolean }) {
  const [loaded, setLoaded] = useState<{ key: string; url: string } | null>(null)
  const [failed, setFailed] = useState('')
  const key = `${product.id}:${product.photo || ''}`
  useEffect(() => {
    if (!product.photo) return
    const controller = new AbortController()
    let url: string | undefined
    fetch(`/api/products/${encodeURIComponent(product.id)}/photo?v=${product.photo}`, { headers: { Authorization: `Bearer ${getStoredToken()}` }, signal: controller.signal, cache: 'no-store' })
      .then(async response => { if (!response.ok) throw new Error(); return response.blob() })
      .then(blob => { if (!controller.signal.aborted) { url = URL.createObjectURL(blob); setLoaded({key, url}) } })
      .catch(() => { if (!controller.signal.aborted) setFailed(key) })
    return () => { controller.abort(); if (url) URL.revokeObjectURL(url) }
  }, [key, product.id, product.photo])
  return <div className={`product-image${large ? ' product-image-large' : ''}`}>
    {loaded?.key === key && failed !== key ? <img src={loaded.url} alt={product.name} onError={() => setFailed(key)} /> : product.photo ? failed === key ? 'Фото недоступно' : <span role="status">Загрузка…</span> : 'Нет фото'}
  </div>
}

export function ProductPhotoEditor({ product, onSaved }: { product: Product; onSaved: () => void }) {
  const [file, setFile] = useState<File | null>(null), [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false), [error, setError] = useState('')
  const submitting = useRef(false)
  if (!product.allowed_actions.includes('EDIT')) return null
  async function save(remove: boolean) {
    if (submitting.current || !reason.trim() || (!remove && !file)) return
    submitting.current = true; setBusy(true); setError('')
    try {
      if (remove) await productCommand(`/${product.id}/photo`, 'DELETE', {expected_version: product.version, reason})
      else {
        const form = new FormData()
        form.append('file', file!); form.append('expected_version', String(product.version)); form.append('reason', reason)
        const response = await fetch(`/api/products/${product.id}/photo`, {method: 'PUT', headers: {Authorization: `Bearer ${getStoredToken()}`}, body: form})
        if (!response.ok) throw new ProductApiError(response.status, true)
      }
      onSaved()
    } catch (error) { setError(error instanceof Error && error.name === 'ProductApiError' ? error.message : 'Не удалось сохранить фотографию. Повторите позже') }
    finally { submitting.current = false; setBusy(false) }
  }
  return <section className="product-knowledge-section product-management"><h2>Фотография изделия</h2><form onSubmit={e => {e.preventDefault(); void save(false)}}><fieldset disabled={busy}>
    <p>JPEG, PNG или WebP, до 10 МБ и 16 млн пикселей. После изменения отметка «Проверено» снимается.</p>
    <label>Файл фотографии<input type="file" accept="image/jpeg,image/png,image/webp" onChange={e => {const selected = e.target.files?.[0] || null; setFile(selected); setError(selected && selected.size > 10 * 1024 * 1024 ? 'Размер фотографии не должен превышать 10 МБ' : '')}} /></label>
    <label>Причина / комментарий<input required maxLength={500} value={reason} onChange={e => setReason(e.target.value)} /></label>
    <div className="product-management-actions"><button disabled={busy || !file || file.size > 10 * 1024 * 1024 || !reason.trim()}>{busy ? 'Сохраняем…' : product.photo ? 'Заменить фотографию' : 'Загрузить фотографию'}</button>{product.photo && <button type="button" disabled={busy || !reason.trim()} onClick={() => void save(true)}>Удалить фотографию</button>}</div>
  </fieldset></form>{error && <p role="alert">{error} <button disabled={busy} onClick={onSaved}>Обновить карточку</button></p>}</section>
}
