import type { Currency, CurrencyTotals, Page, PaymentOccurrence } from './api'

export interface BudgetCurrencyTotals extends CurrencyTotals { forecast: string }
export interface PaymentsBudget {
  year: number; month: number | null; date_from: string; date_to: string; as_of_date: string; timezone: string
  totals: Record<Currency, BudgetCurrencyTotals>
  months: Array<{ month: number; totals: Record<Currency, BudgetCurrencyTotals> }>
}
export interface PaymentReceipt {
  id: string; kind: 'file' | 'link'; url: string | null; filename: string | null
  content_type: 'application/pdf' | 'image/png' | 'image/jpeg' | null
  size_bytes: number | null; uploaded_at: string
}
export interface ReceiptListFilters { query?: string; currency?: Currency; kind?: 'all' | 'file' | 'link' | 'missing'; limit?: number; offset?: number }
export type ReceiptPage = Page<{ occurrence: PaymentOccurrence; receipt: PaymentReceipt | null }>
export interface OneTimePaymentRequest { title: string; amount: string; currency: Currency; due_date: string }
