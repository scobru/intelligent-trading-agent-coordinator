FROM python:3.11-slim

WORKDIR /app

# Disabilita il buffering dell'output Python per visualizzare i log in tempo reale in Docker
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dipendenze di sistema minime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Rimuove eventuali terminazioni Windows (CRLF) e imposta i permessi di esecuzione
RUN dos2unix start.sh && chmod +x start.sh

# Cartella per dati persistenti e database SQLite
RUN mkdir -p /app/data

EXPOSE 3000

CMD ["/bin/bash", "./start.sh"]
