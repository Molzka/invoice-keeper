# Amount and currency editing

## Behaviour

Administrators may edit an unpaid occurrence independently, including an unpaid occurrence of a stopped recurring payment. Paid occurrences remain immutable.

Recurring payment changes start on the first day of the next calendar month in APP_TIMEZONE. Earlier periods, paid periods and periods with individual conditions preserve their stored amount and currency. A future generated occurrence receives the rule's current terms. Currency changes do not perform an exchange-rate conversion.

Input accepts integer units or up to two fractional digits separated by comma or dot. Every request sends an exact two-decimal string and a RUB/USD/EUR code. The UI does not sum different currencies.

## Integrated API implementation

- PATCH /api/v1/payment-occurrences/{id}/amount — JSON {amount, currency}, returns PaymentOccurrence.
- PATCH /api/v1/recurring-payments/{id} — JSON {amount, currency}, returns {payment, effective_from, updated_periods, preserved_custom_periods}.
- Both use the current cookie, CSRF token and administrator authorization.
- PAYMENT_ALREADY_PAID and RECURRING_PAYMENT_STOPPED are conflicts rather than silently accepted edits.
- The existing status/date PATCH contract stays separate.

The drawer prevents duplicate submission and never retries an uncertain mutation automatically. After response loss, it locks further editing until closed so the current server state can be checked. Successful changes refresh lists, summary and calendar.

## Storage and migration

Migration 0009 follows the colleague's audit, receipt, MFA and registration revisions. It backfills amount and currency into existing occurrences, adds constraints and an individual-terms marker, and adds the recurring effective date. Downgrading removes individual period prices, so preserve a database backup before a planned rollback.

## Checks

Frontend mock scenarios cover exact amounts, paid/no-op conflicts, individual conditions, current/history preservation, next-month generation, currency totals, roles and CSRF. PostgreSQL migration and concurrency scenarios passed against an isolated PostgreSQL 17.11 instance. Final checks are recorded in docs/development/technical-verification-2026-10-24.md at repository root.

Snapshot migration 0009 follows MFA revision 0007 and registration revision 0008; lifecycle revision 0010 follows the snapshots. The production extension contract is at repository-root docs/api/payment-lifecycle.md.
