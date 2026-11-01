FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Chain data lives in a volume so it survives updates and restarts.
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "node.py"]
