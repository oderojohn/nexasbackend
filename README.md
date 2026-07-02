# POS Backend

Django REST backend for the POS terminal.

## Setup

```bash
cd backend
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_pos
python manage.py runserver 127.0.0.1:8000
```

## Main Endpoints

- `GET /api/pos/products/?branch=1&search=tusker`
- `GET /api/pos/customers/?search=brian`
- `POST /api/pos/shifts/open/`
- `POST /api/pos/shifts/{id}/close/`
- `POST /api/pos/held-orders/hold/`
- `POST /api/pos/held-orders/{id}/resume/`
- `POST /api/pos/sales/checkout/`
- `POST /api/pos/sales/mpesa/stk-push/`
- `GET /api/pos/sales/`
- `GET /api/pos/sales/{id}/`
- `POST /api/pos/sales/{id}/void/`
- `POST /api/pos/sales/{id}/reprint/`
- `GET /api/pos/sales/summary/`
- `GET /api/pos/stock-movements/`

## Core Rules Implemented

- Only open shifts can post sales.
- Only one open shift is allowed per register.
- Checkout is atomic: sale, items, payments, receipt copy, cash drawer, and stock movement are committed together.
- Stock is locked during checkout and cannot go negative.
- Void is atomic and restores stock.
- Paid sales can be voided once with a required reason.
- Receipt reprint creates an auditable receipt copy number.
- Cash sales update expected drawer cash and voids reverse it.

## M-Pesa Integration

The backend includes a dedicated M-Pesa STK push endpoint:

- `POST /api/pos/sales/mpesa/stk-push/`

Required environment variables:

- `MPESA_CONSUMER_KEY`
- `MPESA_CONSUMER_SECRET`
- `MPESA_BUSINESS_SHORTCODE`
- `MPESA_PASSKEY`
- `MPESA_ENVIRONMENT` (defaults to `sandbox`)
- `MPESA_CALLBACK_URL`
