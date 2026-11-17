import { StrictMode, useEffect, useState, type FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { type Assessment } from './api/assessments'
import { AuthApiError, confirmPasswordReset, ensureCsrf, getCurrentUser, loginUser, logoutUser, registerUser, requestPasswordReset, resendTwoFactor, type AuthUser, verifyTwoFactor } from './api/auth'
import { getV2AdminAssessment, getV2AdminAssessments, getV2AdminResults } from './api/v2Admin'
import { CategoryComparison, ComponentScores, DashboardSummary, ObjectiveIndicators, PendingModules, type AssessmentResults } from './dashboard'
import { AnonymousDemo } from './v2/AnonymousDemo'
import { PersonalModule, type PersonalView } from './v2/PersonalModule'
import './style.css'
import './v2/v2.css'

type AdminSection = 'overview' | 'analytics' | 'testing' | 'reports'
type Route = { role: 'admin'; section: AdminSection } | { role: 'user'; section: PersonalView | 'anonymous' }
type PublicPage = 'login' | 'register' | 'two-factor' | 'reset-request' | 'reset-confirm'

const adminNavigation: { key: AdminSection; label: string; icon: string }[] = [
  { key: 'overview', label: 'Огляд', icon: '◈' }, { key: 'analytics', label: 'Аналітика', icon: '▥' },
  { key: 'testing', label: 'Тестування', icon: '▦' }, { key: 'reports', label: 'Звіти', icon: '↗' },
]
const userNavigation: { key: PersonalView | 'anonymous'; label: string; icon: string }[] = [
  { key: 'profile', label: 'Мій кабінет', icon: '◉' }, { key: 'available', label: 'Мої тестування', icon: '▦' },
  { key: 'attempt', label: 'Поточне тестування', icon: '→' }, { key: 'history', label: 'Мої результати', icon: '↺' },
  { key: 'stats', label: 'Персональна статистика', icon: '▥' }, { key: 'anonymous', label: 'Анонімне опитування', icon: '◎' },
]

function routeFromLocation(): Route {
  const path = window.location.pathname
  if (path === '/app' || path.startsWith('/app/')) {
    const section = path.split('/')[2] as PersonalView | 'anonymous'
    return { role: 'user', section: userNavigation.some((item) => item.key === section) ? section : 'profile' }
  }
  const section = path.split('/')[2] as AdminSection
  return { role: 'admin', section: adminNavigation.some((item) => item.key === section) ? section : 'overview' }
}

function pathFor(route: Route) { return route.role === 'admin' ? `/admin/${route.section}` : `/app/${route.section}` }

function accountInitials(name: string) {
  const initials = name.trim().split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('')
  return initials.toUpperCase() || 'IM'
}

function App() {
  const [route, setRoute] = useState<Route>(() => routeFromLocation())
  const [publicPage, setPublicPage] = useState<PublicPage>(() => window.location.pathname === '/register' ? 'register' : 'login')
  const [session, setSession] = useState<AuthUser | null>(null)
  const [pendingTwoFactor, setPendingTwoFactor] = useState<AuthUser | null>(null)
  const [resetEmail, setResetEmail] = useState('')
  const [authLoading, setAuthLoading] = useState(true)
  const [authError, setAuthError] = useState('')
  const [assessments, setAssessments] = useState<Assessment[]>([])
  const [listLoading, setListLoading] = useState(false)
  const [listError, setListError] = useState('')
  const [listRetry, setListRetry] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [selectedAssessment, setSelectedAssessment] = useState<Assessment | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
  const [detailRetry, setDetailRetry] = useState(0)
  const [results, setResults] = useState<AssessmentResults | null>(null)
  const [resultsLoading, setResultsLoading] = useState(false)
  const [resultsError, setResultsError] = useState('')
  const [resultsRetry, setResultsRetry] = useState(0)
  const isAdmin = route.role === 'admin' && session?.role === 'admin'

  useEffect(() => {
    const onPopState = () => {
      if (['/login', '/register', '/two-factor', '/reset-request', '/reset-confirm'].includes(window.location.pathname)) setPublicPage(window.location.pathname.slice(1) as PublicPage)
      else setRoute(routeFromLocation())
    }
    window.addEventListener('popstate', onPopState)
    if (window.location.pathname === '/') window.history.replaceState(null, '', '/login')
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  useEffect(() => {
    ensureCsrf().catch(() => undefined)
    getCurrentUser().then((response) => { if (response.requires_2fa) { setPendingTwoFactor(response.user); setPublicPage('two-factor') } else setSession(response.user) }).catch((error: unknown) => { if (!(error instanceof AuthApiError && error.status === 401)) setAuthError(error instanceof Error ? error.message : 'Не вдалося перевірити сесію.') }).finally(() => setAuthLoading(false))
  }, [])

  useEffect(() => {
    if (authLoading || !session || !['/login', '/register'].includes(window.location.pathname)) return
    const next: Route = session.role === 'admin' ? { role: 'admin', section: 'overview' } : { role: 'user', section: 'profile' }
    window.history.replaceState(null, '', pathFor(next))
    setRoute(next)
  }, [authLoading, session])

  useEffect(() => {
    if (!isAdmin || !session) { setAssessments([]); setListError(''); setListLoading(false); return }
    const controller = new AbortController()
    setListLoading(true); setListError('')
    getV2AdminAssessments(controller.signal).then(setAssessments).catch((error: unknown) => { if (!controller.signal.aborted) setListError(error instanceof Error ? error.message : 'Не вдалося завантажити цикли.') }).finally(() => { if (!controller.signal.aborted) setListLoading(false) })
    return () => controller.abort()
  }, [isAdmin, session, listRetry])

  useEffect(() => {
    if (!isAdmin || !session || selectedId === null) return
    const controller = new AbortController()
    setSelectedAssessment(null); setDetailLoading(true); setDetailError('')
    getV2AdminAssessment(selectedId, controller.signal).then(setSelectedAssessment).catch((error: unknown) => { if (!controller.signal.aborted) setDetailError(error instanceof Error ? error.message : 'Не вдалося завантажити цикл.') }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false) })
    return () => controller.abort()
  }, [isAdmin, session, selectedId, detailRetry])

  useEffect(() => {
    setResults(null); setResultsError(''); setResultsLoading(false)
    if (!isAdmin || !session || !selectedAssessment || selectedAssessment.id !== selectedId || selectedAssessment.status !== 'closed') return
    const controller = new AbortController()
    setResultsLoading(true)
    getV2AdminResults(selectedAssessment.id, controller.signal).then(setResults).catch((error: unknown) => { if (!controller.signal.aborted) setResultsError(error instanceof Error ? error.message : 'Не вдалося завантажити результати.') }).finally(() => { if (!controller.signal.aborted) setResultsLoading(false) })
    return () => controller.abort()
  }, [isAdmin, session, selectedAssessment, selectedId, resultsRetry])

  function navigate(next: Route) { const nextPath = pathFor(next); if (window.location.pathname !== nextPath) window.history.pushState(null, '', nextPath); setRoute(next) }
  function navigatePublic(page: PublicPage) { window.history.pushState(null, '', `/${page}`); setPublicPage(page) }
  function selectAssessment(value: string) { setSelectedId(value ? Number(value) : null); setSelectedAssessment(null); setDetailError(''); setResults(null); setResultsError('') }
  async function handleLogin(email: string, password: string) { setAuthError(''); try { const response = await loginUser({ email, password }); if (response.requires_2fa) { setPendingTwoFactor(response.user); navigatePublic('two-factor') } else { setSession(response.user); navigate(response.user.role === 'admin' ? { role: 'admin', section: 'overview' } : { role: 'user', section: 'profile' }) } } catch (error) { setAuthError(error instanceof Error ? error.message : 'Не вдалося виконати вхід.') } }
  async function handleRegister(name: string, email: string, password: string, confirmation: string) { setAuthError(''); try { await registerUser({ name, email, password, password_confirmation: confirmation }); navigatePublic('login'); setAuthError('Реєстрацію завершено. Тепер увійдіть до системи.') } catch (error) { setAuthError(error instanceof Error ? error.message : 'Не вдалося створити обліковий запис.') } }
  async function handleTwoFactor(code: string) { setAuthError(''); try { const user = await verifyTwoFactor(code); setPendingTwoFactor(null); setSession(user); navigate(user.role === 'admin' ? { role: 'admin', section: 'overview' } : { role: 'user', section: 'profile' }) } catch (error) { setAuthError(error instanceof Error ? error.message : 'Код не підтверджено.') } }
  async function handleResendTwoFactor() { try { await resendTwoFactor(); setAuthError('Новий код створено. Перевірте налаштований канал доставки.') } catch (error) { setAuthError(error instanceof Error ? error.message : 'Не вдалося повторно надіслати код.') } }
  async function handleResetRequest(email: string) { setAuthError(''); try { await requestPasswordReset(email); setResetEmail(email); navigatePublic('reset-confirm'); setAuthError('Якщо обліковий запис існує, код відновлення створено.') } catch (error) { setAuthError(error instanceof Error ? error.message : 'Не вдалося створити запит.') } }
  async function handleResetConfirm(email: string, code: string, password: string, confirmation: string) { setAuthError(''); try { await confirmPasswordReset({ email, code, password, password_confirmation: confirmation }); navigatePublic('login'); setAuthError('Пароль змінено. Увійдіть із новим паролем.') } catch (error) { setAuthError(error instanceof Error ? error.message : 'Не вдалося змінити пароль.') } }
  async function handleLogout() { try { await logoutUser() } finally { setSession(null); navigatePublic('login') } }

  if (authLoading) return <div className="v2-auth-loading">Перевіряємо сесію…</div>
  if (!session) return <AuthPage page={publicPage} email={resetEmail} error={authError} pendingUser={pendingTwoFactor} onLogin={handleLogin} onRegister={handleRegister} onTwoFactor={handleTwoFactor} onResendTwoFactor={handleResendTwoFactor} onResetRequest={handleResetRequest} onResetConfirm={handleResetConfirm} onSwitch={navigatePublic} />
  if (route.role === 'admin' && session.role !== 'admin') return <RoleDenied user={session} onLogout={handleLogout} />
  if (route.role === 'user' && session.role !== 'user') return <RoleDenied user={session} onLogout={handleLogout} />

  const admin = route.role === 'admin'
  const title = admin ? adminNavigation.find((item) => item.key === route.section)?.label ?? 'Огляд' : userNavigation.find((item) => item.key === route.section)?.label ?? 'Мій кабінет'
  const description = admin ? 'Організаційні агрегати, цикли оцінювання та доступні аналітичні зрізи.' : 'Ваші персональні тестування та результати.'
  return <div className="v2-app"><div className={`v2-shell v2-shell-${route.role}`}><aside className="v2-sidebar"><div className="v2-brand"><span className="v2-brand-mark">IM</span><div><strong>Integrity<br />Management</strong><small>{admin ? 'Адміністративна панель' : 'Особистий простір'}</small></div></div><nav className="v2-nav" aria-label={admin ? 'Навігація адміністратора' : 'Навігація користувача'}><span className="v2-nav-label">{admin ? 'Адміністративна панель' : 'Мій простір'}</span>{(admin ? adminNavigation : userNavigation).map((item) => <button key={item.key} type="button" className={route.section === item.key ? 'is-active' : ''} onClick={() => navigate(admin ? { role: 'admin', section: item.key as AdminSection } : { role: 'user', section: item.key as PersonalView | 'anonymous' })}><span className="v2-nav-icon" aria-hidden="true">{item.icon}</span>{item.label}</button>)}</nav></aside><main className="v2-main"><header className="v2-topbar"><div><p className="v2-overline">Integrity Management · {admin ? 'АДМІНІСТРАТОР' : 'КОРИСТУВАЧ'}</p><h1>{title}</h1><p>{description}</p></div><div className="v2-topbar-actions"><span className="v2-live-status">{admin ? '/admin' : '/app'}</span><div className="v2-account-menu" aria-label="Поточний обліковий запис"><span className="v2-account-avatar" aria-hidden="true">{accountInitials(session.name)}</span><div className="v2-account-details"><strong>{session.name}</strong><span>{admin ? 'Адміністратор' : 'Користувач'}</span><small>{session.email}</small></div><button className="v2-logout-button" type="button" onClick={() => void handleLogout()}>Вийти</button></div></div></header><div className="v2-main-inner">{admin ? <AdminContent assessments={assessments} listLoading={listLoading} listError={listError} setListRetry={setListRetry} selectedId={selectedId} selectedAssessment={selectedAssessment} detailLoading={detailLoading} detailError={detailError} setDetailRetry={setDetailRetry} results={results} resultsLoading={resultsLoading} resultsError={resultsError} setResultsRetry={setResultsRetry} selectAssessment={selectAssessment} section={route.section as AdminSection} /> : route.section === 'anonymous' ? <AnonymousDemo /> : <PersonalModule view={route.section as PersonalView} userId={session.id} userName={session.name} onStart={() => navigate({ role: 'user', section: 'attempt' })} onFinish={() => navigate({ role: 'user', section: 'available' })} />}</div></main></div></div>
}

function AuthPage({ page, email: initialEmail, error, pendingUser, onLogin, onRegister, onTwoFactor, onResendTwoFactor, onResetRequest, onResetConfirm, onSwitch }: { page: PublicPage; email: string; error: string; pendingUser: AuthUser | null; onLogin: (email: string, password: string) => Promise<void>; onRegister: (name: string, email: string, password: string, confirmation: string) => Promise<void>; onTwoFactor: (code: string) => Promise<void>; onResendTwoFactor: () => Promise<void>; onResetRequest: (email: string) => Promise<void>; onResetConfirm: (email: string, code: string, password: string, confirmation: string) => Promise<void>; onSwitch: (page: PublicPage) => void }) {
  const [name, setName] = useState(''); const [email, setEmail] = useState(initialEmail); const [password, setPassword] = useState(''); const [confirmation, setConfirmation] = useState(''); const [code, setCode] = useState(''); const [busy, setBusy] = useState(false)
  async function submit(event: FormEvent) { event.preventDefault(); setBusy(true); try { if (page === 'login') await onLogin(email, password); else if (page === 'register') await onRegister(name, email, password, confirmation); else if (page === 'two-factor') await onTwoFactor(code); else if (page === 'reset-request') await onResetRequest(email); else await onResetConfirm(email, code, password, confirmation) } finally { setBusy(false) } }
  const twoFactor = page === 'two-factor'
  const reset = page === 'reset-request' || page === 'reset-confirm'
  const title = page === 'login' ? 'Вхід до системи' : page === 'register' ? 'Створення облікового запису' : page === 'two-factor' ? 'Підтвердження входу' : page === 'reset-request' ? 'Скидання паролю' : 'Новий пароль'
  const description = page === 'login' ? 'Увійдіть, щоб відкрити персональну або адміністративну панель.' : page === 'register' ? 'Публічна реєстрація створює лише обліковий запис user.' : page === 'two-factor' ? `Код надіслано на ${pendingUser?.email ?? 'вашу пошту'}.` : reset ? 'Введіть код відновлення, отриманий через налаштований канал доставки.' : ''
  return <main className="v2-auth-page"><section className="v2-auth-card"><div className="v2-brand v2-auth-brand"><span className="v2-brand-mark">IM</span><div><strong>Integrity<br />Management</strong><small>Integrity Dashboard</small></div></div><p className="v2-overline">Безпечний вхід</p><h1>{title}</h1><p className="v2-muted">{description}</p>{error && <div className="v2-auth-error" role="alert">{error}</div>}<form onSubmit={submit}>{page === 'register' && <label>Ім’я<input required minLength={2} value={name} onChange={(event) => setName(event.target.value)} /></label>}{!twoFactor && <label>Email<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>}{twoFactor && <label>Код підтвердження<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} /></label>}{reset && page === 'reset-confirm' && <label>Код скидання<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} onChange={(event) => setCode(event.target.value)} /></label>}{(page === 'login' || page === 'register' || page === 'reset-confirm') && <label>Пароль<input required minLength={10} type="password" value={password} onChange={(event) => setPassword(event.target.value)} /><small>Мінімум 10 символів.</small></label>}{(page === 'register' || page === 'reset-confirm') && <label>Підтвердження пароля<input required minLength={10} type="password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>}<button className="v2-button v2-button-primary" disabled={busy} type="submit">{busy ? 'Зачекайте…' : twoFactor ? 'Підтвердити' : page === 'login' ? 'Увійти' : page === 'register' ? 'Зареєструватися' : page === 'reset-request' ? 'Надіслати код' : 'Змінити пароль'}</button></form>{twoFactor && <button className="v2-auth-link" type="button" onClick={() => void onResendTwoFactor()}>Надіслати код повторно</button>}{page === 'login' && <><button className="v2-auth-link" type="button" onClick={() => onSwitch('reset-request')}>Забули пароль?</button><button className="v2-auth-link" type="button" onClick={() => onSwitch('register')}>Створити обліковий запис</button></>}{page !== 'login' && !twoFactor && <button className="v2-auth-link" type="button" onClick={() => onSwitch('login')}>Повернутися до входу</button>}</section></main>
}

function RoleDenied({ user, onLogout }: { user: AuthUser; onLogout: () => Promise<void> }) { return <main className="v2-auth-page"><section className="v2-auth-card"><p className="v2-overline">Доступ обмежено</p><h1>Ця панель недоступна для ролі {user.role}</h1><p className="v2-muted">Серверна роль не дозволяє переглядати цей інтерфейс. Перемикання ролі вручну неможливе.</p><button className="v2-button" type="button" onClick={() => void onLogout()}>Вийти</button></section></main> }

interface AdminContentProps { assessments: Assessment[]; listLoading: boolean; listError: string; setListRetry: (value: number | ((current: number) => number)) => void; selectedId: number | null; selectedAssessment: Assessment | null; detailLoading: boolean; detailError: string; setDetailRetry: (value: number | ((current: number) => number)) => void; results: AssessmentResults | null; resultsLoading: boolean; resultsError: string; setResultsRetry: (value: number | ((current: number) => number)) => void; selectAssessment: (value: string) => void; section: AdminSection }
function AdminContent(props: AdminContentProps) { if (props.section === 'overview') return <Overview {...props} />; if (props.section === 'analytics') return <AdminAnalytics selectedId={props.selectedId} selectedAssessment={props.selectedAssessment} detailLoading={props.detailLoading} detailError={props.detailError} setDetailRetry={props.setDetailRetry} results={props.results} resultsLoading={props.resultsLoading} resultsError={props.resultsError} />; if (props.section === 'testing') return <AdminTesting assessments={props.assessments} selectedId={props.selectedId} selectAssessment={props.selectAssessment} listLoading={props.listLoading} listError={props.listError} />; return <AdminReports /> }

function Overview({ assessments, listLoading, listError, setListRetry, selectedId, selectedAssessment, detailLoading, detailError, setDetailRetry, results, resultsLoading, resultsError, setResultsRetry, selectAssessment }: AdminContentProps) {
  return <>
    <section className="assessment" aria-labelledby="assessment-heading">
      <div className="assessment-heading-row"><div><p className="section-kicker">Адміністративний контекст</p><h2 id="assessment-heading">Цикл оцінювання</h2></div>{selectedAssessment && <span className={`cycle-badge ${selectedAssessment.status === 'open' ? 'cycle-badge-open' : ''}`}>{selectedAssessment.status === 'closed' ? 'Цикл закрито' : 'Цикл відкрито'}</span>}</div>
      {listLoading && <p role="status">Завантажуємо цикли оцінювання…</p>}
      {listError && <div role="alert"><p>{listError}</p><button type="button" onClick={() => setListRetry((value) => value + 1)}>Спробувати ще раз</button></div>}
      {!listLoading && !listError && assessments.length === 0 && <p>Циклів оцінювання поки немає.</p>}
      {!listLoading && !listError && assessments.length > 0 && <div className="assessment-select-wrap"><label htmlFor="assessment-select">Оберіть цикл</label><select id="assessment-select" value={selectedId ?? ''} onChange={(event) => selectAssessment(event.target.value)}><option value="">Оберіть цикл оцінювання</option>{assessments.map((assessment) => <option key={assessment.id} value={assessment.id}>{assessment.name}</option>)}</select></div>}
      {detailLoading && <p role="status">Завантажуємо деталі циклу…</p>}
      {detailError && <div role="alert"><p>{detailError}</p><button type="button" onClick={() => setDetailRetry((value) => value + 1)}>Спробувати ще раз</button></div>}
      {!detailLoading && !detailError && selectedAssessment && <dl className="details"><div><dt>Назва</dt><dd>{selectedAssessment.name}</dd></div><div><dt>Статус</dt><dd>{selectedAssessment.status === 'open' ? 'Відкритий' : 'Закритий'}</dd></div><div><dt>Дата початку</dt><dd>{selectedAssessment.start_date}</dd></div><div><dt>Мінімальний розмір групи</dt><dd>{selectedAssessment.min_group_size}</dd></div></dl>}
      <p className="demo-note">Дані доступні відповідно до ролі та правил конфіденційності.</p>
    </section>
    <section className="dashboard-content">
      <div className="dashboard-intro"><p className="section-kicker">Executive Dashboard</p><h2>Оперативний огляд</h2><p>Коротка картина стану циклу та доступних агрегованих KPI. Детальні розрізи відкриваються в «Аналітиці».</p></div>
      {selectedId === null && <p className="dashboard-state dashboard-state-empty">Оберіть цикл оцінювання, щоб переглянути доступні дані.</p>}
      {detailLoading && <p className="dashboard-state" role="status">Перевіряємо стан циклу…</p>}
      {!detailLoading && !detailError && selectedAssessment?.status === 'open' && <div className="dashboard-state dashboard-state-open" role="status"><strong>Цикл оцінювання ще триває</strong><p>Результати стануть доступними після його закриття.</p></div>}
      {resultsLoading && <p className="dashboard-state" role="status">Завантажуємо агреговані результати…</p>}
      {resultsError && <div className="dashboard-state dashboard-state-error" role="alert"><p>{resultsError}</p><button type="button" onClick={() => setResultsRetry((value) => value + 1)}>Спробувати ще раз</button></div>}
      {!detailLoading && !detailError && !resultsLoading && !resultsError && results && selectedAssessment?.id === results.assessment.id && <DashboardSummary results={results} />}
      {!detailLoading && !detailError && !resultsLoading && !resultsError && results && selectedAssessment?.id === results.assessment.id && <div className="v2-card v2-analysis-teaser"><div><p className="v2-overline">Наступний крок</p><h3>Детальні компоненти, категорії та показники</h3><p className="v2-muted">Перейдіть у «Аналітику», щоб переглянути повну структуру результатів цього циклу.</p></div><span className="v2-pill">Read-only</span></div>}
    </section>
    <PendingModules />
  </>
}

function AdminAnalytics({ selectedId, selectedAssessment, detailLoading, detailError, setDetailRetry, results, resultsLoading, resultsError }: { selectedId: number | null; selectedAssessment: Assessment | null; detailLoading: boolean; detailError: string; setDetailRetry: (value: number | ((current: number) => number)) => void; results: AssessmentResults | null; resultsLoading: boolean; resultsError: string }) { return <section className="v2-admin-grid"><div className="v2-card v2-admin-wide"><div className="v2-section-heading"><div><p className="v2-overline">Детальний read-only аналіз</p><h2>Аналітика циклу</h2>{selectedAssessment && <p className="v2-muted">{selectedAssessment.name} · {selectedAssessment.status === 'open' ? 'Відкритий цикл' : 'Закритий цикл'}</p>}</div><span className="v2-pill">Дані з /results</span></div>{selectedId !== null && detailLoading && <p role="status">Завантажуємо деталі вибраного циклу…</p>}{selectedId !== null && detailError && <div className="v2-empty" role="alert"><strong>Не вдалося завантажити цикл</strong><p className="v2-muted">{detailError}</p><button type="button" className="v2-button" onClick={() => setDetailRetry((value) => value + 1)}>Спробувати ще раз</button></div>}{resultsLoading && !detailLoading && <p role="status">Завантажуємо детальну аналітику…</p>}{resultsError && !detailError && <div className="v2-empty" role="alert"><strong>Аналітика недоступна</strong><p className="v2-muted">{resultsError}</p></div>}{selectedId === null && <div className="v2-empty"><strong>Оберіть цикл в «Огляді»</strong><p className="v2-muted">Графіки будуються лише з фактичних агрегатів закритого циклу.</p></div>}{selectedId !== null && !detailLoading && !detailError && !resultsLoading && !resultsError && !results && selectedAssessment?.status === 'open' && <div className="v2-empty"><strong>Цикл ще відкритий</strong><p className="v2-muted">Детальні агрегати стануть доступними після закриття циклу.</p></div>}{selectedId !== null && !detailLoading && !detailError && !resultsLoading && !resultsError && !results && selectedAssessment?.status === 'closed' && <div className="v2-empty"><strong>Дані ще не завантажені</strong><p className="v2-muted">Поверніться до «Огляду» та повторно оберіть цикл.</p></div>}{results && <><ComponentScores components={results.components} /><CategoryComparison categories={results.categories} components={results.components} /><ObjectiveIndicators components={results.components} /></>}</div><div className="v2-card"><p className="v2-overline">Конфіденційність</p><h3>Захист малих груп активний</h3><p className="v2-muted">Приховані категорії та клітинки не відновлюються через загальні підсумки.</p></div><div className="v2-card"><p className="v2-overline">Майбутня аналітика</p><h3>Comparative Analytics</h3><p className="v2-muted">Очікує окремого погодженого API.</p></div></section> }

function AdminTesting({ assessments, selectedId, selectAssessment, listLoading, listError }: { assessments: Assessment[]; selectedId: number | null; selectAssessment: (value: string) => void; listLoading: boolean; listError: string }) { return <section className="v2-card"><div className="v2-section-heading"><div><p className="v2-overline">Read-only testing registry</p><h2>Доступні цикли</h2></div><span className="v2-pill">Без керування опитуваннями</span></div>{listLoading && <p role="status">Завантажуємо цикли…</p>}{listError && <p className="v2-muted" role="alert">{listError}</p>}{!listLoading && !listError && <div className="v2-cycle-list">{assessments.map((assessment) => <button type="button" className={selectedId === assessment.id ? 'v2-cycle-item is-selected' : 'v2-cycle-item'} key={assessment.id} onClick={() => selectAssessment(String(assessment.id))}><span><strong>{assessment.name}</strong><small>{assessment.start_date} · мінімальна група {assessment.min_group_size}</small></span><span className={assessment.status === 'open' ? 'v2-cycle-status is-open' : 'v2-cycle-status'}>{assessment.status === 'open' ? 'Відкритий' : 'Закритий'}</span></button>)}</div>}</section> }
function AdminReports() { return <section className="v2-content-grid"><div className="v2-card v2-report-placeholder"><p className="v2-overline">Reporting module</p><h2>Звітна інформація</h2><p className="v2-muted">Доступний лише перегляд дозволених агрегатів Dashboard.</p><span className="v2-pill v2-pill-warm">PDF / XLSX очікують Reporting API</span></div><div className="v2-card"><p className="v2-overline">Безпечний режим</p><h3>Фальшиві експорти вимкнені</h3><p className="v2-muted">Кнопки завантаження з’являться лише після погодження серверного формату та приватності.</p></div></section> }

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
