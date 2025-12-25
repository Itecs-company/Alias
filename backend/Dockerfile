FROM python:3.11

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir socksio \
    && pip install --no-cache-dir "httpx[socks]==0.26.0"

COPY app ./app

ENV STORAGE_DIR=/data/storage \
    DATABASE_URL=sqlite+aiosqlite:////data/alias.db

EXPOSE 8024

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8024"]
