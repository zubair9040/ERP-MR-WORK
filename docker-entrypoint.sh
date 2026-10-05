#!/bin/sh
# On a throw-away test host (ERP_DEMO=1), load sample data if the database is empty.
if [ "$ERP_DEMO" = "1" ]; then
  python manage.py demo || true
fi
exec gunicorn -w 2 --threads 4 --timeout 600 -b 0.0.0.0:${PORT:-8000} wsgi:app
