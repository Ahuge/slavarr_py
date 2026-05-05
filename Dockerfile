# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHON_PATH=$PYTHON_PATH:/app/src

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

# data volume for sqlite db
VOLUME ["/app/data"]

ENV PORT=3001
EXPOSE 3001

WORKDIR /app/src
CMD ["python","/app/src/discord_app/main.py"]
