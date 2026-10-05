FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV ERP_DATA_DIR=/data ERP_HTTPS=1 PYTHONUNBUFFERED=1
VOLUME /data
EXPOSE 8000
CMD ["gunicorn", "-w", "2", "--threads", "4", "--timeout", "600", "-b", "0.0.0.0:8000", "wsgi:app"]
