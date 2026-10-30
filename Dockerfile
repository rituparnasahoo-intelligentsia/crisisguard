# ---------- Single stage: Python API ----------
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

CMD ["sh", "-c", "python -m scripts.init_db && uvicorn backend.api:app --host 0.0.0.0 --port 8000"]