FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

ARG GCP_SECRET_FILE=gcp-secret.json
COPY ${GCP_SECRET_FILE} ./
ENV GCP_SECRET_FILE=/app/${GCP_SECRET_FILE}

COPY app.py logger.py ./

RUN mkdir -p logs

CMD ["uv", "run", "python", "app.py"]
