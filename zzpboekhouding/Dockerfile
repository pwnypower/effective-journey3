FROM python:3.12-slim

WORKDIR /app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .
COPY run.py /app/run.py

# Persistente data (database) komt in de add-on data map
ENV DB_PATH=/data/boekhouding.db
ENV PORT=5000

CMD ["python", "run.py"]
