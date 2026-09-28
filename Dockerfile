FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# poppler-utils gives the resume uploader PDF support (pdftotext); curl is for the health check
RUN apt-get update && apt-get install -y --no-install-recommends curl poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p jobhunt/output

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -sf http://127.0.0.1:8000/health/ || exit 1

# Binds 0.0.0.0 inside the container; publish the port only to localhost (see docker-compose.yml)
CMD ["sh", "-c", "cd django_project && python manage.py migrate --noinput && python manage.py runserver 0.0.0.0:8000"]
