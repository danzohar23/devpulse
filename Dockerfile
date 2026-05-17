FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY src/ src/

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "pulse.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
