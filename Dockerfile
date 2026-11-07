FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=7860

RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY portfolio_agent portfolio_agent
COPY data data
COPY database_schema.sql .
COPY reports reports

# Build the database into the image: fast start-up, and the running app only reads it.
RUN python -c "from portfolio_agent.config import Settings; from portfolio_agent.db import build_database; build_database(Settings())"
RUN chown -R app:app /app

USER app
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import os,urllib.request as u; u.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=2)"

# One process is enough: requests run in a thread pool and spend their time waiting on the model.
CMD ["sh", "-c", "exec uvicorn portfolio_agent.api:app --host 0.0.0.0 --port ${PORT}"]
