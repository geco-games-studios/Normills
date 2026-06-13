# Normils Ecommerce UAT Documentation

## 1. Document Control

| Item | Details |
| --- | --- |
| Project | Normils Ecommerce Marketplace |
| Document Type | User Acceptance Testing Documentation |
| Version | 1.0 |
| Prepared For | Normils / Geco Games Studios |
| Prepared By | Project Team |
| Test Environment | Staging or production-like environment |
| Target Users | Customers, store/admin users |

## 2. Purpose

This User Acceptance Testing document defines the business workflows, test scenarios, expected outcomes, and sign-off criteria for the Normils ecommerce platform.

The goal is to confirm that the system is ready for real customers to browse products, manage accounts, use wishlist, place orders, pay with mobile money, track payment status, and allow admins to review orders and payments.

## 3. Scope

### In Scope

- User registration and login
- Profile management
- Product browsing and search
- Product filtering
- Product detail view
- Cart management
- Wishlist add/remove and count display
- Mobile and desktop navigation
- Checkout with mobile money
- Lenco payment processing states
- Order history and order confirmation
- Django admin order/payment visibility
- Admin payment refresh from Lenco

### Out of Scope

- Third-party Lenco service availability guarantees
- Bank settlement reconciliation outside Lenco response data
- Store owner inventory workflows not exposed to customers
- Load testing and performance benchmarking
- Security penetration testing

## 4. UAT Entry Criteria

Testing can begin when:

- The latest code has been deployed to the UAT environment.
- Database migrations have been applied.
- Static/media files are served correctly.
- Lenco API credentials are configured.
- Test products, categories, and users exist.
- Testers have access to customer and admin accounts.

## 5. UAT Exit Criteria

UAT can be signed off when:

- All critical test cases pass.
- No open Severity 1 or Severity 2 defects remain.
- Business owner accepts any known low-risk issues.
- Payment flows have been verified with successful and failed Lenco responses.
- Admin can identify paid, processing, and failed orders.

## 6. Tester Roles

| Role | Responsibility |
| --- | --- |
| Customer Tester | Tests shopping, wishlist, profile, checkout, and order flows |
| Admin Tester | Tests Django admin order/payment management |
| Business Owner | Confirms workflows match business expectations |
| Technical Support | Reviews defects and confirms fixes |

## 7. Test Data

| Data Type | Example |
| --- | --- |
| Customer Account | customer@example.com |
| Admin Account | admin user with Django admin access |
| Product | White Striped Crop Tee |
| Payment Method | Mobile Money |
| Operators | Airtel Money, MTN Mobile Money |
| Test Amount | ZMW 9.51 or current cart total |
| Lenco Statuses | pending, pay-offline, successful, failed, 3ds-auth-required |

## 8. Severity Levels

| Severity | Meaning | Example |
| --- | --- | --- |
| S1 Critical | Blocks core business operation | Customer cannot checkout |
| S2 High | Major feature broken with no easy workaround | Paid orders never show as paid |
| S3 Medium | Feature issue with workaround | Wishlist count delays until refresh |
| S4 Low | Cosmetic or minor wording issue | Label alignment issue |

## 9. Test Cases

### 9.1 User Registration and Login

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| AUTH-001 | Register a new customer | Open signup, enter valid details, submit, verify OTP if required | User account is created and can log in | Not Run |
| AUTH-002 | Login with email | Enter registered email and password | User is logged in and redirected correctly | Not Run |
| AUTH-003 | Login with phone | Enter registered phone and password | User is logged in successfully | Not Run |
| AUTH-004 | Invalid login | Enter wrong password | Error message is shown, user remains logged out | Not Run |
| AUTH-005 | Duplicate email safety | Login where duplicate email exists but password matches one user | Correct user logs in, no server error | Not Run |

### 9.2 Profile Management

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| PROF-001 | Open profile page | Click Account in desktop nav | Profile page opens | Not Run |
| PROF-002 | Open profile on mobile | Open mobile menu, tap Account | Profile page opens | Not Run |
| PROF-003 | Edit first and last name | Update first name and last name, save | Names are saved and shown on profile/nav | Not Run |
| PROF-004 | Upload profile picture | Choose image and save profile | Profile picture is uploaded and displayed | Not Run |
| PROF-005 | Change password | Enter current password, new password, confirmation | Password changes and user remains logged in | Not Run |
| PROF-006 | Invalid password change | Enter wrong current password | Validation error is shown | Not Run |

### 9.3 Product Browsing and Search

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| PROD-001 | View home page products | Open home page | Products display correctly | Not Run |
| PROD-002 | Search products | Search for `shirt` | Page shows `Search Results for "shirt"` and relevant products | Not Run |
| PROD-003 | Empty search | Submit empty search | No server error; empty/no-results state appears | Not Run |
| PROD-004 | View product details | Click a product | Product detail page opens with image, price, stock, cart controls | Not Run |
| PROD-005 | Category page | Open a category | Products in that category are shown | Not Run |

### 9.4 Wishlist

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| WISH-001 | Add product to wishlist | Click heart icon on product card | Heart becomes highlighted and wishlist count increases | Not Run |
| WISH-002 | Persistent highlighted icon | Add product, leave page, return | Product heart remains highlighted | Not Run |
| WISH-003 | Desktop wishlist count | Add/remove wishlist item | Desktop wishlist badge updates | Not Run |
| WISH-004 | Mobile wishlist link | Open mobile menu | Wishlist link appears with count | Not Run |
| WISH-005 | Remove from wishlist page | Open wishlist, click heart on item | Item is removed from wishlist page | Not Run |
| WISH-006 | Empty wishlist state | Remove last wishlist item | Empty wishlist message appears | Not Run |

### 9.5 Cart

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| CART-001 | Add item to cart | Add product from detail/category page | Product is added to cart | Not Run |
| CART-002 | Update quantity | Increase/decrease quantity in cart | Cart totals update correctly | Not Run |
| CART-003 | Remove item | Remove item from cart | Item is removed and totals update | Not Run |
| CART-004 | Empty cart checkout | Try checkout with empty cart | User is prevented from checking out | Not Run |

### 9.6 Checkout and Mobile Money

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| PAY-001 | Mobile money only | Open checkout | Mobile Money is selected; Cash on Delivery is disabled/faded | Not Run |
| PAY-002 | Payment charge display | Select Mobile Money | ZMW 8.50 + 1% mobile money charge appears under tax/charge area | Not Run |
| PAY-003 | Submit checkout | Fill required details, place order | Processing modal opens and payment request is sent | Not Run |
| PAY-004 | Lenco pending | Lenco returns `pending` | Order is created with Payment: Processing | Not Run |
| PAY-005 | Lenco pay-offline | Lenco returns `pay-offline` | User is told to authorize on phone; order remains Processing | Not Run |
| PAY-006 | Lenco successful | Lenco returns `successful` | Order shows Paid/Completed and cart is cleared | Not Run |
| PAY-007 | Lenco failed | Lenco returns `failed` | Payment failed message appears; order shows Failed | Not Run |
| PAY-008 | Insufficient balance | Customer has insufficient mobile money balance | Failed or processing status is shown according to Lenco response | Not Run |
| PAY-009 | No phone approval | Customer does not approve prompt | Order remains Processing until Lenco reports failed/successful | Not Run |
| PAY-010 | Duplicate submit prevention | Click Place Order repeatedly | Button is disabled during processing; duplicate orders are prevented | Not Run |

### 9.7 Order History and Confirmation

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| ORD-001 | View order history | Open My Orders | Orders list displays order status and payment status separately | Not Run |
| ORD-002 | Paid order display | Open paid order | Page shows Payment complete / Paid | Not Run |
| ORD-003 | Processing order display | Open processing order | Page shows Waiting for payment / Processing | Not Run |
| ORD-004 | Failed order display | Open failed order | Page shows Payment failed / Failed | Not Run |
| ORD-005 | Payment reference | Open order details | Payment reference is visible | Not Run |
| ORD-006 | Auto payment check | Open processing order | Page checks payment status automatically | Not Run |

### 9.8 Django Admin

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| ADM-001 | View orders in admin | Open Django admin > Store > Orders | Orders list displays order/payment columns | Not Run |
| ADM-002 | Payment fields visible | Open an order detail | payment_method, payment_status, payment_reference, payment_details are visible | Not Run |
| ADM-003 | Filter by payment status | Use payment status filter | Orders are filtered correctly | Not Run |
| ADM-004 | Search payment reference | Search by Lenco/payment reference | Matching order is found | Not Run |
| ADM-005 | Refresh from Lenco | Select order, run Refresh selected orders from Lenco | Payment status updates from latest Lenco response | Not Run |
| ADM-006 | Confirm successful refresh | Lenco response has `successful` | Django order becomes Paid/Completed | Not Run |
| ADM-007 | Confirm failed refresh | Lenco response has `failed` | Django order becomes Failed | Not Run |

### 9.9 Responsive Navigation

| ID | Test Case | Steps | Expected Result | Status |
| --- | --- | --- | --- | --- |
| NAV-001 | Desktop account menu | Hover Account | Dropdown remains visible while selecting links | Not Run |
| NAV-002 | Desktop account click | Click Account | Profile page opens | Not Run |
| NAV-003 | Mobile menu | Open hamburger menu | Home, Cart, Wishlist, Account, Orders links are visible | Not Run |
| NAV-004 | Mobile account click | Tap Account | Profile page opens for logged-in users | Not Run |
| NAV-005 | Guest mobile account | Logged out, tap Account | Login page opens | Not Run |

## 10. Defect Log Template

| Defect ID | Test Case ID | Severity | Description | Steps to Reproduce | Expected | Actual | Owner | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| DEF-001 |  |  |  |  |  |  |  | Open |

## 11. UAT Sign-Off

| Name | Role | Decision | Signature | Date |
| --- | --- | --- | --- | --- |
|  | Business Owner | Accepted / Rejected |  |  |
|  | Project Lead | Accepted / Rejected |  |  |
|  | Technical Lead | Accepted / Rejected |  |  |

## 12. Notes

- Payment status in Django depends on Lenco response data. If Lenco later changes a transaction from pending to successful, the system must refresh payment status through the customer order page or admin refresh action.
- Production must have a valid `LENCO_API_KEY`.
- After deploying profile picture support, run database migrations before testing profile updates.
