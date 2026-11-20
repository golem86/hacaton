import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { paginate, pageTokens, shownLabel, type Page } from './testList'
import './test-list.css'

/** Розміри сторінки для довгих списків адміністратора й користувача. */
export const LIST_PAGE_SIZES = [10, 25, 50] as const

/**
 * Стан пагінації для будь-якого списку. Сторінка обмежується діапазоном, а `resetKey`
 * (наприклад, рядок фільтрів або id циклу) повертає на першу сторінку при зміні умов.
 */
export function usePagination<T>(items: readonly T[], { pageSize: initialSize = LIST_PAGE_SIZES[0], resetKey = '' }: { pageSize?: number; resetKey?: string } = {}) {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(initialSize)
  useEffect(() => { setPage(1) }, [resetKey])
  const current: Page<T> = useMemo(() => paginate(items, page, pageSize), [items, page, pageSize])
  return {
    current,
    setPage,
    setPageSize: (size: number) => { setPageSize(size); setPage(1) },
  }
}

interface PagerProps {
  page: number
  pageCount: number
  label: string
  onPageChange: (page: number) => void
}

/** Навігація сторінками: «Попередня», номери з «…» та «Наступна». Поточна сторінка має aria-current="page". */
export function Pager({ page, pageCount, label, onPageChange }: PagerProps) {
  if (pageCount <= 1) return null
  return (
    <nav className="test-list__pager" aria-label={label}>
      <button className="v2-button test-list__pager-step" type="button" disabled={page <= 1} onClick={() => onPageChange(page - 1)}>
        <span aria-hidden="true">←</span> Попередня
      </button>
      <ol className="test-list__pages">
        {pageTokens(page, pageCount).map((token) => typeof token === 'number' ? (
          <li key={token}>
            <button
              className={token === page ? 'v2-button test-list__page is-current' : 'v2-button test-list__page'}
              type="button"
              aria-label={`Сторінка ${token} з ${pageCount}`}
              aria-current={token === page ? 'page' : undefined}
              onClick={() => { if (token !== page) onPageChange(token) }}
            >
              {token}
            </button>
          </li>
        ) : (
          <li key={token} className="test-list__ellipsis" aria-hidden="true">…</li>
        ))}
      </ol>
      <button className="v2-button test-list__pager-step" type="button" disabled={page >= pageCount} onClick={() => onPageChange(page + 1)}>
        Наступна <span aria-hidden="true">→</span>
      </button>
    </nav>
  )
}

interface ListPaginationProps<T> {
  /** Результат `usePagination(...).current`. */
  current: Page<T>
  onPageChange: (page: number) => void
  onPageSizeChange: (size: number) => void
  /** Назва списку для підписів доступності, напр. «журналу дій». */
  name: string
  pageSizes?: readonly number[]
  children: ReactNode
}

/**
 * Обгортка списку з пагінацією зверху й знизу. Зверху — «Показано 1–10 з 37», розмір сторінки
 * та номери сторінок; знизу — ті самі номери. Після переходу знизу список прокручується до початку.
 */
export function ListPagination<T>({ current, onPageChange, onPageSizeChange, name, pageSizes = LIST_PAGE_SIZES, children }: ListPaginationProps<T>) {
  const id = useId()
  const topRef = useRef<HTMLDivElement>(null)
  const go = (page: number, fromBottom: boolean) => {
    onPageChange(page)
    if (fromBottom && typeof window !== 'undefined') {
      const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
      topRef.current?.scrollIntoView({ block: 'start', behavior: reduce ? 'auto' : 'smooth' })
    }
  }
  const sizes = pageSizes.includes(current.pageSize) ? pageSizes : [...pageSizes, current.pageSize].sort((a, b) => a - b)
  return (
    <div className="list-pagination">
      <div className="list-pagination__bar" ref={topRef}>
        <p className="test-list__count" role="status">{shownLabel(current)}</p>
        {current.total > Math.min(...pageSizes) && (
          <div className="test-list__page-size">
            <label htmlFor={`${id}-size`}>На сторінці</label>
            <select id={`${id}-size`} value={current.pageSize} onChange={(event) => onPageSizeChange(Number(event.target.value))}>
              {sizes.map((size) => <option key={size} value={size}>{size}</option>)}
            </select>
          </div>
        )}
      </div>
      <Pager page={current.page} pageCount={current.pageCount} label={`Сторінки ${name} (угорі)`} onPageChange={(page) => go(page, false)} />
      {children}
      <Pager page={current.page} pageCount={current.pageCount} label={`Сторінки ${name} (унизу)`} onPageChange={(page) => go(page, true)} />
    </div>
  )
}
