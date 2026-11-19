import { StrictMode, useEffect, useState, type FormEvent } from 'react'
import { createRoot } from 'react-dom/client'
import { getAssessment, getAssessments, type Assessment } from './api/assessments'
import { getAuditEvents, type AuditEvent } from './api/admin'
import {
  confirmPasswordReset, ensureCsrf, getCurrentUser, loginUser, logoutUser, registerUser,
  requestPasswordReset, resendTwoFactor, verifyTwoFactor, type AuthUser,
} from './api/auth'
import { getAssessmentResults } from './dashboard/results'
import { CategoryComparison, ComponentScores, DashboardSummary, ObjectiveIndicators, PendingModules, type AssessmentResults } from './dashboard'
import { AnalyticsModules } from './dashboard/AnalyticsModules'
import { PersonalModule, type PersonalView } from './v2/PersonalModule'
import { pathForPublicPage, publicPageFromPath, type PublicPage } from './v2/publicRoutes'
import Survey from './pages/Survey'
import AssessmentManager from './components/AssessmentManager'
import './style.css'
import './v2/v2.css'

type AdminSection = 'overview' | 'analytics' | 'testing' | 'audit' | 'reports'
type Route = { role: 'admin'; section: AdminSection } | { role: 'user'; section: PersonalView }
const adminItems: { key: AdminSection; title: string }[] = [
  { key: 'overview', title: 'Огляд' }, { key: 'analytics', title: 'Аналітика' },
  { key: 'testing', title: 'Тестування' }, { key: 'audit', title: 'Audit Trail' }, { key: 'reports', title: 'Звіти' },
]
const userItems: { key: PersonalView; title: string }[] = [
  { key: 'profile', title: 'Мій кабінет' }, { key: 'available', title: 'Мої тестування' },
  { key: 'attempt', title: 'Поточне тестування' }, { key: 'history', title: 'Мої результати' }, { key: 'stats', title: 'Персональна статистика' },
]

function routeFromPath(path: string): Route {
  const [root, section] = path.split('/').filter(Boolean)
  if (root === 'app') return { role: 'user', section: userItems.some(x => x.key === section) ? section as PersonalView : 'profile' }
  return { role: 'admin', section: adminItems.some(x => x.key === section) ? section as AdminSection : 'overview' }
}
function go(path: string) { history.pushState({}, '', path); window.dispatchEvent(new PopStateEvent('popstate')) }
function homeFor(user: AuthUser) { return user.role === 'admin' ? '/admin' : '/app' }

function App() {
  const [path, setPath] = useState(location.pathname)
  const [page, setPage] = useState<PublicPage>(() => publicPageFromPath(location.pathname))
  const [session, setSession] = useState<AuthUser | null>(null)
  const [pendingUser, setPendingUser] = useState<AuthUser | null>(null)
  const [pendingEmail, setPendingEmail] = useState('')
  const [initializing, setInitializing] = useState(true)
  const [authError, setAuthError] = useState('')
  const [resetNotice, setResetNotice] = useState('')
  useEffect(() => {
    const onPop = () => { setPath(location.pathname); setPage(publicPageFromPath(location.pathname)) }
    const onExpired = () => { setSession(null); setPendingUser(null); setAuthError('Сесію завершено. Увійдіть знову.'); setPage('login'); go('/login'); void ensureCsrf().catch(() => {}) }
    window.addEventListener('popstate', onPop)
    window.addEventListener('v2-session-expired', onExpired)
    void ensureCsrf().then(() => getCurrentUser()).then(result => {
      if (result.requires_2fa) { setPendingUser(result.user); setPendingEmail(result.user.email ?? ''); setPage('two-factor') }
      else { setSession(result.user); if (location.pathname === '/login' || location.pathname === '/register' || location.pathname === '/') go(homeFor(result.user)) }
    }).catch(() => {}).finally(() => setInitializing(false))
    return () => { window.removeEventListener('popstate', onPop); window.removeEventListener('v2-session-expired', onExpired) }
  }, [])

  async function signIn(email: string, password: string) {
    setAuthError('')
    try {
      const result = await loginUser({ email, password })
      setPendingUser(result.user); setPendingEmail(email); go(pathForPublicPage('two-factor'))
    } catch (error) { setAuthError(error instanceof Error ? error.message : 'Не вдалося увійти.') }
  }
  async function verify(code: string) {
    setAuthError('')
    try { const user = await verifyTwoFactor(code); setSession(user); setPendingUser(null); go(homeFor(user)) }
    catch (error) { setAuthError(error instanceof Error ? error.message : 'Не вдалося підтвердити вхід.') }
  }
  async function signUp(name: string, email: string, password: string, confirmation: string) {
    setAuthError('')
    try { await registerUser({ name, email, password, password_confirmation: confirmation }); setAuthError('Запит прийнято. Якщо обліковий запис можна створити, інструкція надійде через налаштований канал.'); setPage('login'); go('/login') }
    catch (error) { setAuthError(error instanceof Error ? error.message : 'Не вдалося зареєструватися.') }
  }
  async function signOut() {
    try { await logoutUser() } finally { setSession(null); setPendingUser(null); await ensureCsrf().catch(() => {}); go('/login'); setPage('login') }
  }
  if (initializing) return <main className="v2-auth-page"><p role="status">Перевіряємо захищену сесію…</p></main>
  if (path === '/survey') return <PublicSurvey />
  if (!session) return <AuthPage page={page} pendingEmail={pendingEmail} error={authError} notice={resetNotice} pendingUser={pendingUser}
    onLogin={signIn} onRegister={signUp} onVerify={verify} onResend={() => resendTwoFactor().then(() => setAuthError('Код повторно надіслано.'))}
    onResetRequest={async email => { setAuthError(''); await requestPasswordReset(email); setResetNotice('Якщо адреса зареєстрована, інструкція надійде через налаштований канал.'); go(pathForPublicPage('reset-confirm')) }}
    onResetConfirm={async (email, code, password, confirmation) => { await confirmPasswordReset({ email, code, password, password_confirmation: confirmation }); setAuthError('Пароль оновлено. Увійдіть із новим паролем.'); go(pathForPublicPage('login')) }}
    onSwitch={next => { setAuthError(''); setResetNotice(''); go(pathForPublicPage(next)) }} />

  const route = routeFromPath(path)
  if (route.role !== session.role) return <RoleDenied user={session} onLogout={signOut} />
  const admin = session.role === 'admin'
  const section = route.section
  const title = admin ? adminItems.find(x => x.key === section)?.title ?? 'Огляд' : userItems.find(x => x.key === section)?.title ?? 'Мій кабінет'
  return <div className="v2-app"><div className={`v2-shell v2-shell-${session.role}`}>
    <aside className="v2-sidebar"><div className="v2-brand"><span className="v2-brand-mark">IM</span><div><strong>Integrity<br/>Management</strong><small>{admin ? 'Адміністративна панель' : 'Особистий простір'}</small></div></div>
      <nav className="v2-nav" aria-label={admin ? 'Навігація адміністратора' : 'Навігація користувача'}><span className="v2-nav-label">{admin ? 'Адміністрування' : 'Мій простір'}</span>
        {(admin ? adminItems : userItems).map(item => <button key={item.key} className={section === item.key ? 'is-active' : ''} onClick={() => go(admin ? `/admin/${item.key}` : `/app/${item.key}`)} type="button">{item.title}</button>)}
        {admin && <button type="button" onClick={() => go('/survey')}>Анонімний Survey ↗</button>}
      </nav>
    </aside>
    <main className="v2-main"><header className="v2-topbar"><div><p className="v2-overline">Integrity Management · {admin ? 'АДМІНІСТРАТОР' : 'КОРИСТУВАЧ'}</p><h1>{title}</h1><p>{admin ? 'Організаційні агрегати з Survey API та Analytics.' : 'Ваші особисті тестування й результати.'}</p></div>
      <div className="v2-account-menu"><span className="v2-account-avatar">{session.name.trim().slice(0, 2).toUpperCase()}</span><div className="v2-account-details"><strong>{session.name}</strong><span>{admin ? 'Адміністратор' : 'Користувач'}</span><small>{session.email}</small></div><button className="v2-logout-button" onClick={() => void signOut()} type="button">Вийти</button></div>
    </header><div className="v2-main-inner">
      {admin ? <AdminPanel section={section as AdminSection} /> : <PersonalModule view={section as PersonalView} userId={session.id} userName={session.name} onStart={() => go('/app/attempt')} onFinish={() => go('/app/history')} />}
    </div></main>
  </div></div>
}

function AuthPage(props: { page: PublicPage; pendingEmail: string; error: string; notice: string; pendingUser: AuthUser | null; onLogin: (e: string,p: string) => Promise<void>; onRegister: (n:string,e:string,p:string,c:string)=>Promise<void>; onVerify:(c:string)=>Promise<void>; onResend:()=>Promise<void>; onResetRequest:(e:string)=>Promise<void>; onResetConfirm:(e:string,c:string,p:string,pc:string)=>Promise<void>; onSwitch:(p:PublicPage)=>void }) {
  const [name,setName]=useState(''),[email,setEmail]=useState(props.pendingEmail),[password,setPassword]=useState(''),[confirmation,setConfirmation]=useState(''),[code,setCode]=useState(''),[busy,setBusy]=useState(false)
  const submit=async (event:FormEvent)=>{event.preventDefault();setBusy(true);try { if(props.page==='login') await props.onLogin(email,password); else if(props.page==='register') await props.onRegister(name,email,password,confirmation); else if(props.page==='two-factor') await props.onVerify(code); else if(props.page==='reset-request') await props.onResetRequest(email); else await props.onResetConfirm(email,code,password,confirmation) } finally {setBusy(false)} }
  const title:Record<PublicPage,string>={login:'Вхід до системи',register:'Створення облікового запису','two-factor':'Підтвердження входу','reset-request':'Скидання паролю','reset-confirm':'Новий пароль'}
  return <main className="v2-auth-page"><section className="v2-auth-card"><div className="v2-brand v2-auth-brand"><span className="v2-brand-mark">IM</span><div><strong>Integrity<br/>Management</strong><small>Integrity Dashboard</small></div></div><p className="v2-overline">Захищений доступ</p><h1>{title[props.page]}</h1><p className="v2-muted">{props.page==='two-factor'?`Код підтвердження надіслано на ${props.pendingEmail}.`:props.page==='register'?'Публічна реєстрація створює лише обліковий запис user.':'Увійдіть, щоб відкрити панель відповідно до серверної ролі.'}</p>
    {(props.error||props.notice)&&<div className="v2-auth-error" role="status">{props.error||props.notice}</div>}
    <form onSubmit={submit}>{props.page==='register'&&<label>Ім’я<input required minLength={2} value={name} onChange={e=>setName(e.target.value)}/></label>}{props.page!=='two-factor'&&<label>Email<input required type="email" value={email} onChange={e=>setEmail(e.target.value)}/></label>}{(props.page==='two-factor'||props.page==='reset-confirm')&&<label>Код підтвердження<input required inputMode="numeric" pattern="[0-9]{6}" maxLength={6} value={code} onChange={e=>setCode(e.target.value)}/></label>}{['login','register','reset-confirm'].includes(props.page)&&<label>Пароль<input required minLength={10} type="password" value={password} onChange={e=>setPassword(e.target.value)}/><small>Мінімум 10 символів.</small></label>}{['register','reset-confirm'].includes(props.page)&&<label>Підтвердження пароля<input required minLength={10} type="password" value={confirmation} onChange={e=>setConfirmation(e.target.value)}/></label>}<button className="v2-button v2-button-primary" disabled={busy}>{busy?'Зачекайте…':props.page==='two-factor'?'Підтвердити':props.page==='login'?'Увійти':props.page==='register'?'Зареєструватися':props.page==='reset-request'?'Надіслати код':'Змінити пароль'}</button></form>
    {props.page==='two-factor'&&<button className="v2-auth-link" type="button" onClick={()=>void props.onResend()}>Надіслати код повторно</button>}{props.page==='login'&&<><button className="v2-auth-link" type="button" onClick={()=>props.onSwitch('reset-request')}>Забули пароль?</button><button className="v2-auth-link" type="button" onClick={()=>props.onSwitch('register')}>Створити обліковий запис</button></>}{props.page!=='login'&&<button className="v2-auth-link" type="button" onClick={()=>props.onSwitch('login')}>Повернутися до входу</button>}
  </section></main>
}

function RoleDenied({user,onLogout}:{user:AuthUser;onLogout:()=>Promise<void>}) { return <main className="v2-auth-page"><section className="v2-auth-card"><h1>Доступ обмежено</h1><p>Роль {user.role} не має доступу до цієї панелі. Дозволи перевіряються сервером.</p><button className="v2-button" onClick={()=>void onLogout()}>Вийти</button></section></main> }
function PublicSurvey() { const [assessments,setAssessments]=useState<Assessment[]>([]),[selected,setSelected]=useState(''),[error,setError]=useState(''); useEffect(()=>{const c=new AbortController();getAssessments(c.signal).then(setAssessments).catch(e=>{if(!c.signal.aborted)setError(e instanceof Error?e.message:'Не вдалося завантажити цикли')});return()=>c.abort()},[]); return <main className="page"><header className="page-header"><p className="eyebrow">Анонімне опитування</p><h1>Survey</h1><p>Потрібен одноразовий код. Подання не пов’язується з обліковим записом.</p><a href="/login">Вхід адміністратора</a></header>{error&&<p role="alert">{error}</p>}<label htmlFor="survey-cycle">Цикл оцінювання</label><select id="survey-cycle" value={selected} onChange={e=>setSelected(e.target.value)}><option value="">Оберіть цикл</option>{assessments.filter(a=>a.status==='open').map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select>{selected?<Survey key={selected} assessmentId={Number(selected)}/>:<p>Оберіть доступний відкритий цикл.</p>}</main> }

function AdminPanel({section}:{section:AdminSection}) { const [assessments,setAssessments]=useState<Assessment[]>([]),[id,setId]=useState<number|null>(null),[detail,setDetail]=useState<Assessment|null>(null),[results,setResults]=useState<AssessmentResults|null>(null),[error,setError]=useState(''),[loading,setLoading]=useState(true),[events,setEvents]=useState<AuditEvent[]>([])
  useEffect(()=>{const c=new AbortController();getAssessments(c.signal).then(list=>{setAssessments(list);if(list.length)setId(list[0].id)}).catch(e=>setError(e instanceof Error?e.message:'Помилка API')).finally(()=>setLoading(false));return()=>c.abort()},[])
  useEffect(()=>{if(id===null)return;const c=new AbortController();setDetail(null);setResults(null);setError('');getAssessment(id,c.signal).then(a=>{if(c.signal.aborted)return;setDetail(a);if(a.status==='closed')getAssessmentResults(id,c.signal).then(setResults).catch(e=>{if(!c.signal.aborted)setError(e instanceof Error?e.message:'Не вдалося завантажити результати')})}).catch(e=>{if(!c.signal.aborted)setError(e instanceof Error?e.message:'Не вдалося завантажити цикл')});return()=>c.abort()},[id])
  useEffect(()=>{if(section!=='audit')return;const c=new AbortController();getAuditEvents(c.signal).then(setEvents).catch(e=>setError(e instanceof Error?e.message:'Не вдалося завантажити журнал'));return()=>c.abort()},[section])
  if(section==='audit')return <section className="v2-card"><h2>Audit Trail</h2>{error&&<p role="alert">{error}</p>}{events.length?events.map(e=><article className="v2-history-item" key={e.id}><strong>{e.action}</strong><span>{e.created_at} · {e.actor_role} · цикл {e.assessment_id??'—'}</span></article>):!error&&<p>Записів поки немає.</p>}</section>
  if(section==='reports')return <section className="v2-card"><h2>Звіти</h2><p>Доступні агрегати показані в аналітиці. PDF/XLSX експорт очікує серверного Reporting API.</p><p>Експорт повертає HTTP 501 до затвердження формату.</p></section>
  if(section==='testing')return <AssessmentManager />
  return <>{assessments.length>0&&<label className="cycle-select">Цикл оцінювання<select value={id??''} onChange={e=>setId(Number(e.target.value)||null)}>{assessments.map(a=><option key={a.id} value={a.id}>{a.name}</option>)}</select></label>}{error&&<div role="alert" className="v2-auth-error">{error}</div>}{section==='overview'&&<><h2>Оперативний огляд</h2>{results?<DashboardSummary results={results}/>:<p>{detail?.status==='open'?'Результати стануть доступними після закриття циклу.':loading?'Завантаження…':'Оберіть цикл.'}</p>}<PendingModules/></>}{section==='analytics'&&<><h2>Агреговані результати</h2>{results?<><ComponentScores components={results.components}/><CategoryComparison categories={results.categories} components={results.components}/><ObjectiveIndicators components={results.components}/>{detail?.status==='closed'&&id&&<AnalyticsModules id={id} assessments={assessments}/>}</>:<p>{detail?.status==='open'?'Цикл відкритий: агрегати недоступні до закриття.':loading?'Завантаження…':'Результатів немає.'}</p>}</>}</>
}

createRoot(document.getElementById('root')!).render(<StrictMode><App/></StrictMode>)
