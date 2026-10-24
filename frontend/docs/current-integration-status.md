# Integration status

Based on main 5548e8aab00bf12320e70e2e2e53746d00a6b313 (including PR #29 documentation updates). Aeza redesign, themes and layout fixes are reconciled with the colleague's session, timezone, audit, receipt and budget changes.

Production navigation includes payments, calendar, recurring rules, history, budget and receipts; audit and users remain administrator-only. Budget reads /payments/budget, activity reads /audit-events, receipts use the per-occurrence routes plus the paginated /payment-receipts collection. Real mode never falls back to demo data.

One-time creation, admin amount/currency editing and preserved deletion are implemented in frontend, mock transport and backend. Stopping remains separate from deletion. Cancelled periods are viewable in history but cannot be changed; totals/forecast exclude them and the generator preserves their tombstones.

Budget and receipt filters persist in the hash URL. Forecast is separate from stored obligations. Cookie/Origin/CSRF protection covers raw file PUTs. Unknown mutation outcomes require checking state before a manual repeat.

Migrations: 0005 audit, 0006 receipts, 0007 amount snapshots, 0008 lifecycle. Apply all before starting this frontend. Contract: repository-root docs/api/payment-lifecycle.md and backend/openapi.json.

design-preview.html remains a development-only presentation sandbox; it is not used for production navigation or data. Final verification results are recorded separately.
