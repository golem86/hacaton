import { getAssessmentResults } from './results'
import type { AssessmentResults } from './types'

/** Ignore even a late response from a transport that does not honor abort. */
export function loadResults(
  id: number,
  onSuccess: (results: AssessmentResults) => void,
  onError: (message: string) => void,
  onDone: () => void,
): () => void {
  const controller = new AbortController()
  getAssessmentResults(id, controller.signal)
    .then((results) => {
      if (!controller.signal.aborted) onSuccess(results)
    })
    .catch((error: unknown) => {
      if (!controller.signal.aborted) onError(error instanceof Error ? error.message : 'Не вдалося завантажити результати.')
    })
    .finally(() => {
      if (!controller.signal.aborted) onDone()
    })
  return () => controller.abort()
}
