import { useState } from 'react'
import { roleLabel, type AuthUser } from '../api/auth'

/**
 * Меню облікового запису для будь-якої автентифікованої ролі:
 * «Вийти» (поточна сесія) і «Вийти на всіх пристроях» (POST /v2/auth/logout-all, з підтвердженням).
 */
export function AccountMenu({ user, onLogout, onLogoutAll }: {
  user: Pick<AuthUser, 'name' | 'email' | 'role'>
  onLogout: () => void
  onLogoutAll: () => Promise<void>
}) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function logoutEverywhere() {
    setBusy(true)
    setError('')
    try {
      await onLogoutAll()
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Не вдалося завершити сесії.')
      setBusy(false)
    }
  }

  return (
    <div className="v2-topbar-actions">
      <div className="v2-account-menu">
        <span className="v2-account-avatar">{user.name.trim().slice(0, 2).toUpperCase()}</span>
        <div className="v2-account-details"><strong>{user.name}</strong><span>{roleLabel(user.role)}</span><small>{user.email}</small></div>
        <button className="v2-logout-button" onClick={onLogout} type="button">Вийти</button>
      </div>
      {confirming ? (
        <div className="v2-logout-all-confirm" role="group" aria-label="Підтвердження виходу на всіх пристроях">
          <span>Завершити всі ваші сесії на всіх пристроях?</span>
          <button className="v2-logout-button" type="button" disabled={busy} onClick={() => void logoutEverywhere()}>{busy ? 'Завершуємо…' : 'Так, вийти всюди'}</button>
          <button className="v2-logout-button v2-logout-button-quiet" type="button" disabled={busy} onClick={() => { setConfirming(false); setError('') }}>Скасувати</button>
        </div>
      ) : (
        <button className="v2-logout-all-button" type="button" onClick={() => setConfirming(true)}>Вийти на всіх пристроях</button>
      )}
      {error && <p className="v2-auth-error" role="alert">{error}</p>}
    </div>
  )
}
