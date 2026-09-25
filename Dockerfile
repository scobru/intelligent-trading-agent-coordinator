FROM python:3.11-slim

WORKDIR /app

# Disabilita il buffering dell'output Python per visualizzare i log in tempo reale in Docker
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Dipendenze di sistema minime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Rimuove eventuali terminazioni Windows (CRLF) e imposta i permessi di esecuzione
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh

EXPOSE 3000

CMD ["bash", "./start.sh"]
