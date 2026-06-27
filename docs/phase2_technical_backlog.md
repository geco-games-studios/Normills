# Mazabuka by Normils Phase 2 Technical Backlog

This backlog converts the Phase 2 requirements into implementable epics while preserving the current MVP.

## Stabilization Gate

Before Phase 2 feature work starts, keep the MVP baseline green:

- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- `python manage.py test`
- production secrets configured through environment variables
- generated artifacts kept out of version control
- staging deployment able to run migrations and `collectstatic`

## Epic 1: Roles, Permissions, and Trust

Goal: replace ad hoc account flags with explicit user roles and trust states.

First slices:

- Define roles: customer, merchant, verified merchant, delivery partner, admin, finance admin, moderator, support officer.
- Add permission checks for dashboard actions instead of one broad dashboard gate.
- Add merchant/customer verification state.
- Add trust badges: verified merchant, premium merchant, top seller, fast delivery, PayGo eligible, trusted business.

Acceptance checks:

- regular customers cannot access merchant/admin workflows
- support and moderator users have scoped permissions
- trust badges are stored separately from display text

## Epic 2: Merchant Centre

Goal: make store management feel like posting on social media from a phone.

First slices:

- mobile-first product creation flow
- image upload, compression, and resizing
- suggested categories, brands, and tags
- product draft, publish, duplicate, pause
- merchant inventory and sales dashboard
- merchant payout visibility

Acceptance checks:

- a merchant can publish a simple product in under two minutes
- advanced fields remain optional
- image uploads produce web-safe sizes

## Epic 3: Share-Ready Product Marketing

Goal: every product becomes marketing-ready by default.

First slices:

- generate product share metadata on publish
- generate square social card
- generate portrait WhatsApp Status/Stories card
- generate WhatsApp ad copy
- add QR code or product link
- store generated share assets per product

Acceptance checks:

- generated cards include product image, brand, merchant, price, CTA, and PayGo estimate when available
- share text is available from product detail and merchant centre

## Epic 4: PayGo

Goal: add responsible PayGo financing without weakening checkout reliability.

First slices:

- PayGo eligibility rules
- PayGo application model
- approval/rejection workflow
- agreement and repayment schedule
- repayment payment tracking
- finance admin dashboard

Acceptance checks:

- PayGo applications are auditable
- repayment state is separate from normal order payment state
- finance admins can review approvals and repayment health

## Epic 5: Deals and Negotiation

Goal: support customer-merchant negotiation before purchase.

First slices:

- Start Deal button on eligible products
- buyer/merchant deal thread
- offer and counter-offer records
- accepted deal agreement
- payment from accepted deal
- completion and delivery state

Acceptance checks:

- deal messages cannot mutate agreed prices after acceptance
- accepted deals can be traced to orders/payments

## Epic 6: Discovery and Browsing

Goal: make browsing effortless and locally relevant.

First slices:

- infinite scroll
- recently viewed products
- trending products/posts
- nearby merchants
- saved searches
- product comparison
- PayGo eligibility filter

Acceptance checks:

- browsing works well on mobile
- filters can be combined without server errors
- recommendation fallbacks work when no personalized data exists

## Epic 7: Wallet, Payouts, and Referrals

Goal: support platform-level money movement and growth loops.

First slices:

- wallet and wallet transaction models
- merchant payout records
- referral code and attribution
- referral conversion tracking
- admin reconciliation views

Acceptance checks:

- wallet transactions are append-only
- payout state changes are auditable
- referral conversion is linked to a user/order event

## Epic 8: Delivery and Notifications

Goal: make order fulfillment visible and trackable.

First slices:

- delivery partner profile
- delivery assignment
- pickup, dispatched, delivered states
- customer notifications
- merchant notifications
- support escalation notes

Acceptance checks:

- delivery state changes are timestamped
- customers and merchants see consistent order state

## Epic 9: Moderation and Support

Goal: keep the marketplace trustworthy as community features grow.

First slices:

- report product/store/user
- moderation queue
- support ticket model
- internal notes
- audit trail for moderation actions

Acceptance checks:

- moderators cannot access finance-only workflows
- moderation actions are logged with actor and timestamp

## Epic 10: Analytics

Goal: measure growth, merchant success, and PayGo health.

First slices:

- registered users
- monthly active users
- verified users
- merchant growth
- product listings
- orders and GMV
- PayGo approvals
- PayGo repayment rate
- referral conversions
- average order value
- customer lifetime value
- merchant retention

Acceptance checks:

- analytics definitions are documented
- dashboards separate raw totals from reset/baseline-adjusted numbers
