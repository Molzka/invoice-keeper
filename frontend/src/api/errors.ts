import type { ErrorDetail } from '../types/api'

export interface ApiRequestContext { method: string; path: string }

/** HTTP context is optional for backwards compatibility; it never contains query or request data. */
export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: ErrorDetail[] = [], public request?: ApiRequestContext, public retryAfterSeconds?: number) {
    super(message); this.name = 'ApiError'
  }
}

const paymentCollectionPaths = new Set(['/payments/summary', '/payment-occurrences', '/recurring-payments'])

/** A missing collection route is an integration problem, not an empty dataset or an absent item. */
export function isMissingPaymentRoute(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 404 && error.request?.method === 'GET' && paymentCollectionPaths.has(error.request.path)
}
