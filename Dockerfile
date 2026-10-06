# Hosted demo. Runs in public mode: private sandbox per visitor, invite-only live calls.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PUBLIC_MODE=1 PYTHONUNBUFFERED=1

# Hosts like Railway pass the port in $PORT.
CMD uvicorn webapp.app:app --host 0.0.0.0 --port ${PORT:-8000}
