# 1. Wir nutzen ein offizielles, extrem schlankes Python-Image als Basis
FROM python:3.12-slim

# 2. Wir setzen das Arbeitsverzeichnis im Container
WORKDIR /app

# 3. Wir kopieren ERST die Einkaufsliste in den Container...
COPY requirements.txt .

# 4. ...und installieren die Pakete (ohne unnötigen Cache-Müll zu behalten)
RUN pip install --no-cache-dir -r requirements.txt

# 5. JETZT kopieren wir unseren restlichen Code (main.py, index.html) rein
COPY . .

# 6. Wir öffnen Port 8000 für die Außenwelt
EXPOSE 8000

# 7. Der Befehl, der ausgeführt wird, wenn der Container startet
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]