# PayGo Technical Requirements

## Purpose

PayGo lets a customer request structured payment terms for an eligible product without changing the normal checkout, Lenco payment, delivery, or merchant payout foundations. The first MVP keeps approval manual so finance/admin can control risk before automation is added.

## Actors

- Customer: applies for PayGo on an eligible product, pays the deposit, then repays over the agreed term.
- Finance/admin: reviews applications, approves or rejects them, tracks repayment health, and resolves arrears.
- Merchant: receives the order through the existing order and fulfillment path once a PayGo application is approved and activated.
- Platform: stores eligibility, repayment state, missed payment state, and credit improvement evidence.

## Eligibility Check

A product is PayGo available only when all of these are true:

- `Product.paygo_eligible` is true.
- The product is published.
- The product is available.
- Online stock is greater than zero.
- The product price is greater than zero.

The product carries the first PayGo terms:

- `paygo_min_deposit_percent`
- `paygo_term_months`
- `paygo_credit_improvement_points`

## Application States

- Submitted: customer has requested PayGo review.
- Approved: finance/admin accepted the request, but the PayGo order is not active yet.
- Rejected: finance/admin declined the request with an audit note.
- Active: deposit has been paid and the customer is now in repayment.
- In arrears: at least one repayment is missed.
- Completed: outstanding balance is fully settled.
- Cancelled: application was stopped before completion.

## Financial Fields

- Requested price: product price at application time.
- Deposit required: minimum deposit calculated from the product PayGo settings.
- Deposit paid: confirmed upfront payment amount.
- Term months: repayment term copied from the product PayGo settings unless finance/admin adjusts it.
- Outstanding balance: requested price minus deposit paid and paid repayments.
- Missed payment count: count of repayment rows marked missed.

## Repayment Schedule

Each PayGo application can create repayment rows with:

- sequence number
- due date
- amount due
- amount paid
- payment/reference note
- status: pending, paid, missed, or waived

Repayment state must remain separate from normal `Order.payment_status`. Normal order payment confirms checkout/deposit/fulfillment. PayGo repayment health confirms the customer's financing performance after activation.

## Completion And Credit Improvement

When outstanding balance reaches zero:

- application status becomes completed
- credit improvement points can be awarded
- `credit_score_after` may be calculated from `credit_score_before + credit_points_awarded`

If a repayment is missed:

- repayment status becomes missed
- missed payment count increases
- an active application moves to in arrears

## MVP Automation Boundary

For item 5, the customer only needs to choose PayGo on an eligible product and submit an application. Finance/admin can approve or reject manually in admin. Automated scoring, automated repayment collection, and automated credit bureau reporting are later phases.
