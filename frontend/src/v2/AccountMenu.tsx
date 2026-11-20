import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { roleLabel, type AuthUser } from '../api/auth'
import { DevicesIcon, LogOutIcon } from './icons'

/** Ініціали для аватара: перші літери двох слів імені або дві перші літери одного слова. */
export function accountInitials(name: string): string {
  const [first = '', second = ''] = name.trim().split(/\s+/)
  if (!first) return '?'
  return (second ? first.charAt(0) + second.charAt(0) : first.slice(0, 2)).toUpperCase()
}

/**
 * Меню облікового запису для будь-якої автентифікованої ролі:
 * «Вийти» (поточна сесія) і «Вийти на всіх пристроях» (POST /v2/auth/logout-all, з підтвердженням).
 * `compact`: мобільний варіант — круглий аватар у рядку логотипа, дані й виходи у спливному меню.
 */
export function AccountMenu({ user, onLogout, onLogoutAll, compact = false }: {
  user: Pick<AuthUser, 'name' | 'email' | 'role'>
  onLogout: () => void
  onLogoutAll: () => Promise<void>
  compact?: boolean
}) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const cancelRef = useRef<HTMLButtonElement>(null)
  const logoutAllRef = useRef<HTMLButtonElement>(null)
  const pendingFocus = useRef<'cancel' | 'logout-all' | null>(null)

  // Фокус не губиться, коли кнопка «Вийти на всіх пристроях» змінюється на підтвердження і назад.
  useEffect(() => {
    const target = pendingFocus.current
    pendingFocus.current = null
    if (target === 'cancel') cancelRef.current?.focus()
    else if (target === 'logout-all') logoutAllRef.current?.focus()
  }, [confirming])

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

  const initials = accountInitials(user.name)
  const role = roleLabel(user.role)
  const logoutAll = confirming ? (
    <div className="v2-logout-all-confirm" role="group" aria-label="Підтвердження виходу на всіх пристроях">
      <span>Завершити всі ваші сесії на всіх пристроях?</span>
      <button className="v2-logout-button" type="button" disabled={busy} onClick={() => void logoutEverywhere()}>{busy ? 'Завершуємо…' : 'Так, вийти всюди'}</button>
      <button ref={cancelRef} className="v2-logout-button v2-logout-button-quiet" type="button" disabled={busy} onClick={() => { pendingFocus.current = 'logout-all'; setConfirming(false); setError('') }}>Скасувати</button>
    </div>
  ) : (
    <button ref={logoutAllRef} className="v2-logout-all-button" type="button" onClick={() => { pendingFocus.current = 'cancel'; setConfirming(true) }}>
      {compact && <DevicesIcon size={18} />}Вийти на всіх пристроях
    </button>
  )
  const errorMessage = error && <p className="v2-auth-error" role="alert">{error}</p>

  if (compact) {
    return (
      <AccountPopover initials={initials} label={`Обліковий запис: ${user.name}`} title={`${user.name} · ${role}`}
        onOpen={() => { if (!busy) { setConfirming(false); setError('') } }}>
        <div className="v2-account-popover-head">
          <span className="v2-account-avatar" aria-hidden="true">{initials}</span>
          <div className="v2-account-details"><strong>{user.name}</strong><span>{role}</span><small>{user.email}</small></div>
        </div>
        <button className="v2-logout-button v2-account-logout" onClick={onLogout} type="button"><LogOutIcon size={18} />Вийти</button>
        {logoutAll}
        {errorMessage}
      </AccountPopover>
    )
  }

  return (
    <div className="v2-topbar-actions">
      <div className="v2-account-menu">
        <span className="v2-account-avatar">{initials}</span>
        <div className="v2-account-details"><strong>{user.name}</strong><span>{role}</span><small>{user.email}</small></div>
        <button className="v2-logout-button" onClick={onLogout} type="button">Вийти</button>
      </div>
      {logoutAll}
      {errorMessage}
    </div>
  )
}

/**
 * Кнопка-аватар і спливне меню (не модальне). Закривається кліком поза меню, Escape, переходом фокуса
 * назовні та навігацією (popstate). Під час відкриття фокус переходить у меню, після Escape — на аватар.
 */
function AccountPopover({ initials, label, title, onOpen, children }: {
  initials: string
  label: string
  title: string
  onOpen: () => void
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const panelId = `${useId()}account-menu`
  const rootRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    panelRef.current?.querySelector<HTMLElement>('button:not([disabled])')?.focus()
    const close = () => setOpen(false)
    const onPointerDown = (event: PointerEvent) => { if (!rootRef.current?.contains(event.target as Node)) close() }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      close()
      triggerRef.current?.focus()
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('popstate', close)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('popstate', close)
    }
  }, [open])

  return (
    <div className="v2-account-compact" ref={rootRef} onBlur={event => {
      const next = event.relatedTarget
      if (open && next instanceof Node && !event.currentTarget.contains(next)) setOpen(false)
    }}>
      <button ref={triggerRef} className="v2-account-trigger" type="button" aria-haspopup="dialog" aria-expanded={open}
        aria-controls={panelId} aria-label={label} title={title} onClick={() => { if (!open) onOpen(); setOpen(!open) }}>
        <span aria-hidden="true">{initials}</span>
      </button>
      <div ref={panelRef} id={panelId} className="v2-account-popover" role="dialog" aria-label="Обліковий запис" hidden={!open}>
        {children}
      </div>
    </div>
  )
}
