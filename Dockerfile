FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV LIPPERSHEY_DB=/data/lippershey.db
ENV LIPPERSHEY_CONFIG=/app/config.yaml
VOLUME /data
EXPOSE 8000
CMD ["python", "server.py"]
