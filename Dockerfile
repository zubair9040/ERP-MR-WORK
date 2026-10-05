FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV ERP_DATA_DIR=/data ERP_HTTPS=1 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
CMD ["sh", "/app/docker-entrypoint.sh"]
