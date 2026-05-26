FROM python:3.13-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen --no-dev

COPY bot.py logger.py gcp-key.json ./

RUN mkdir -p logs

CMD ["uv", "run", "python", "bot.py"]
