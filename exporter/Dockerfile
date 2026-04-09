FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY parser.py exporter.py ./

ENV IN_CLUSTER=true
ENV NAMESPACE=services
ENV POD_PREFIX=cfs-
ENV CONTAINER_NAME=ansible
ENV BATCH_INTERVAL=2
ENV BATCH_SIZE=100

CMD ["python", "-u", "exporter.py"]
