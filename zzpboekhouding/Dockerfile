FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libreoffice-writer \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
COPY run.py /app/run.py

# Persistente data — /data/ overleeft updates, /app/ niet
ENV DB_PATH=/data/boekhouding.db
ENV TEMPLATE_PAD=/data/factuur_template.docx
ENV PORT=5000

CMD ["python", "run.py"]
