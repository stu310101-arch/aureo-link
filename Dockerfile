FROM python:3.12-slim
WORKDIR /opt/aureo
COPY requirements-server.txt ./
RUN pip install --no-cache-dir -r requirements-server.txt
COPY server ./server
COPY pwa ./pwa
ENV AUREO_HOST=0.0.0.0 AUREO_PORT=8787 AUREO_DB_PATH=/data/hub.sqlite3
EXPOSE 8787
CMD ["python", "-m", "server.app"]
