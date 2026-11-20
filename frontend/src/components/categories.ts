/** Категорії респондентів циклу (коди backend) та їхні назви в інтерфейсі керування циклами. */
export const categoryLabels = { mgmt: 'Керівництво', npp: 'Науково-педагогічні працівники', cadets: 'Курсанти', staff: 'Працівники' } as const
export type Category = keyof typeof categoryLabels
export const ALL_CATEGORIES = Object.keys(categoryLabels) as Category[]

/** Назва категорії; невідомий код показується як є. */
export function categoryLabel(code: string): string {
  return Object.hasOwn(categoryLabels, code) ? categoryLabels[code as Category] : code
}
