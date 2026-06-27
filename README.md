# Normills MVP

Normills is a Django ecommerce MVP for product browsing, customer accounts, cart, checkout, mobile money payment tracking, order operations, and merchant/admin management.

## Local Setup

1. Create a virtual environment.

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

2. Install dependencies.

   ```powershell
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   ```

3. Create local environment settings.

   ```powershell
   Copy-Item .env.example .env
   ```

4. Apply migrations and run checks.

   ```powershell
   python manage.py migrate
   python manage.py check
   python manage.py test
   ```

5. Start the development server.

   ```powershell
   python manage.py runserver
   ```

## Stabilization Baseline

Before building Phase 2 features, keep these checks green:

- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- `python manage.py test`

Production and staging secrets must be configured through environment variables, not committed to the repository. Start from `.env.example` for the full list of required settings.

## Deployment Notes

- Run `python manage.py migrate` before deploying application code that depends on schema changes.
- Run `python manage.py collectstatic --noinput` for production static assets.
- Configure `DJANGO_DEBUG=False`, secure cookie flags, real `DJANGO_ALLOWED_HOSTS`, and real `DJANGO_CSRF_TRUSTED_ORIGINS` in production.
- Configure `LENCO_API_KEY`, `EXCITESMS_API_TOKEN`, SMTP credentials, and WhatsApp credentials only in the deployment environment.
