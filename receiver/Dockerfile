FROM node:22-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

COPY receiver/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY receiver/app.py receiver/models.py ./
COPY --from=frontend-build /frontend/dist ./static

ENV DB_PATH=/data/cfs_logs.db
ENV API_KEY=changeme

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
