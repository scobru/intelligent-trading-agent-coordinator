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

# Permessi di esecuzione per lo script di avvio
RUN chmod +x start.sh

EXPOSE 3000

CMD ["./start.sh"]
