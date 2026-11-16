export function scoreText(score: number | null): string {
  return score === null ? 'Немає даних' : `${score.toLocaleString('uk-UA', { maximumFractionDigits: 1 })} зі 100`
}

export function categoryName(code: string): string {
  const names: Record<string, string> = {
    cadets: 'Курсанти',
    mgmt: 'Керівництво',
    npp: 'Науково-педагогічні працівники',
    staff: 'Персонал',
  }
  return names[code] ?? code
}

export function barWidth(score: number): string {
  return `${Math.max(0, Math.min(100, score))}%`
}
