FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Nebulite's physics, so this node can check scouts itself (docker compose passes the "nebulite" context;
# by hand: docker build --build-context nebulite=../nebulite .)
COPY --from=nebulite trajectory.py config.py vsop87a.txt star_targets.json ./nebulite/
# Chain data lives in a volume so it survives updates and restarts.
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
VOLUME /data
CMD ["python", "node.py"]
