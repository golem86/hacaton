import { useId } from 'react'
import {
  PAGE_SIZES,
  SORT_OPTIONS,
  STATUS_OPTIONS,
  pageTokens,
  type SortKey,
  type StatusFilter,
  type TestListFilters,
} from './testList'
import './test-list.css'

interface FiltersProps {
  filters: TestListFilters
  sort: SortKey
  activeCount: number
  expanded: boolean
  onToggle: () => void
  onChange: (patch: Partial<TestListFilters>) => void
  onSortChange: (sort: SortKey) => void
  onReset: () => void
}

/** Пошук, фільтри та сортування списку тестувань. На мобільному фільтри згортаються під кнопку «Фільтри». */
export function TestListFilterPanel({ filters, sort, activeCount, expanded, onToggle, onChange, onSortChange, onReset }: FiltersProps) {
  const id = useId()
  const panelId = `${id}-panel`
  return (
    <div className="test-list__controls" role="search" aria-label="Пошук і фільтри тестувань">
      <div className="test-list__search-row">
        <div className="test-list__field test-list__field--search">
          <label htmlFor={`${id}-query`}>Пошук за назвою</label>
          <input
            id={`${id}-query`}
            type="search"
            value={filters.query}
            placeholder="Наприклад, Q1 2026 або канали"
            autoComplete="off"
            enterKeyHint="search"
            onChange={(event) => onChange({ query: event.target.value })}
          />
        </div>
        <div className="test-list__field test-list__field--sort">
          <label htmlFor={`${id}-sort`}>Сортування</label>
          <select id={`${id}-sort`} value={sort} onChange={(event) => onSortChange(event.target.value as SortKey)}>
            {SORT_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </div>
        <button
          className="v2-button v2-button-quiet test-list__toggle"
          type="button"
          aria-expanded={expanded}
          aria-controls={panelId}
          onClick={onToggle}
        >
          {activeCount ? `Фільтри (${activeCount})` : 'Фільтри'}
          <span className="test-list__toggle-mark" aria-hidden="true">{expanded ? '▴' : '▾'}</span>
        </button>
      </div>
      <div id={panelId} className={expanded ? 'test-list__panel is-expanded' : 'test-list__panel'}>
        <div className="test-list__field">
          <label htmlFor={`${id}-status`}>Статус</label>
          <select id={`${id}-status`} value={filters.status} onChange={(event) => onChange({ status: event.target.value as StatusFilter })}>
            {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </div>
        <fieldset className="test-list__range">
          <legend>Дата створення</legend>
          <div className="test-list__range-inputs">
            <div className="test-list__field">
              <label htmlFor={`${id}-created-from`}>від</label>
              <input id={`${id}-created-from`} type="date" value={filters.createdFrom} max={filters.createdTo || undefined} onChange={(event) => onChange({ createdFrom: event.target.value })} />
            </div>
            <div className="test-list__field">
              <label htmlFor={`${id}-created-to`}>до</label>
              <input id={`${id}-created-to`} type="date" value={filters.createdTo} min={filters.createdFrom || undefined} onChange={(event) => onChange({ createdTo: event.target.value })} />
            </div>
          </div>
        </fieldset>
        <fieldset className="test-list__range">
          <legend>Дедлайн</legend>
          <div className="test-list__range-inputs">
            <div className="test-list__field">
              <label htmlFor={`${id}-deadline-from`}>від</label>
              <input id={`${id}-deadline-from`} type="date" value={filters.deadlineFrom} max={filters.deadlineTo || undefined} onChange={(event) => onChange({ deadlineFrom: event.target.value })} />
            </div>
            <div className="test-list__field">
              <label htmlFor={`${id}-deadline-to`}>до</label>
              <input id={`${id}-deadline-to`} type="date" value={filters.deadlineTo} min={filters.deadlineFrom || undefined} onChange={(event) => onChange({ deadlineTo: event.target.value })} />
            </div>
          </div>
        </fieldset>
        <div className="test-list__panel-actions">
          <button className="v2-button v2-button-quiet test-list__reset" type="button" disabled={!activeCount} onClick={onReset}>Скинути фільтри</button>
        </div>
      </div>
    </div>
  )
}

interface PageSizeProps {
  pageSize: number
  onChange: (size: number) => void
}

export function TestListPageSize({ pageSize, onChange }: PageSizeProps) {
  const id = useId()
  return (
    <div className="test-list__page-size">
      <label htmlFor={`${id}-size`}>На сторінці</label>
      <select id={`${id}-size`} value={pageSize} onChange={(event) => onChange(Number(event.target.value))}>
        {PAGE_SIZES.map((size) => <option key={size} value={size}>{size}</option>)}
      </select>
    </div>
  )
}

interface PaginationProps {
  page: number
  pageCount: number
  onPageChange: (page: number) => void
}

/** Навігація сторінками: «Попередня», номери з «…» та «Наступна». Поточна сторінка має aria-current="page". */
export function TestListPagination({ page, pageCount, onPageChange }: PaginationProps) {
  if (pageCount <= 1) return null
  return (
    <nav className="test-list__pager" aria-label="Сторінки списку тестувань">
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
