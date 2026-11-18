export type PublicPage = 'login' | 'register' | 'two-factor' | 'reset-request' | 'reset-confirm'

const pathByPage: Record<PublicPage, string> = {
  login: '/login',
  register: '/register',
  'two-factor': '/login/2fa',
  'reset-request': '/login/reset',
  'reset-confirm': '/login/reset/confirm',
}

export function publicPageFromPath(path: string): PublicPage {
  switch (path) {
    case '/register': return 'register'
    case '/login/2fa': return 'two-factor'
    case '/login/reset': return 'reset-request'
    case '/login/reset/confirm': return 'reset-confirm'
    default: return 'login'
  }
}

export function pathForPublicPage(page: PublicPage): string {
  return pathByPage[page]
}
