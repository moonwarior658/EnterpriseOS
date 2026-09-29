import { useState } from 'react'
import {
  copyGeneratedPassword,
  passwordInputType,
  passwordToggleLabel,
} from '../utils/passwordUx'

type GeneratedCredentialsPanelProps = {
  username: string
  temporaryPassword: string
  onClose: () => void
}

export function GeneratedCredentialsPanel({
  username,
  temporaryPassword,
  onClose,
}: GeneratedCredentialsPanelProps) {
  const [visible, setVisible] = useState(false)
  const [copyStatus, setCopyStatus] = useState('')

  async function copyPassword() {
    try {
      await copyGeneratedPassword(temporaryPassword)
      setCopyStatus('Пароль скопирован')
    } catch {
      setCopyStatus('Не удалось скопировать пароль')
    }
  }

  return (
    <section className="generated-credentials" aria-live="polite">
      <div>
        <h2>Данные для входа</h2>
        <p>Сохраните пароль сейчас. После закрытия этого блока получить его снова нельзя.</p>
      </div>
      <dl>
        <div><dt>Логин:</dt><dd>{username}</dd></div>
        <div>
          <dt>Временный пароль:</dt>
          <dd>
            <input
              aria-label="Временный пароль"
              readOnly
              type={passwordInputType(visible)}
              value={temporaryPassword}
            />
          </dd>
        </div>
      </dl>
      <div className="user-actions">
        <button className="secondary-action" type="button" onClick={() => setVisible((value) => !value)}>
          {passwordToggleLabel(visible)}
        </button>
        <button className="secondary-action" type="button" onClick={() => void copyPassword()}>
          Скопировать пароль
        </button>
        <button className="secondary-action" type="button" onClick={onClose}>
          Закрыть
        </button>
      </div>
      {copyStatus && <p>{copyStatus}</p>}
    </section>
  )
}
