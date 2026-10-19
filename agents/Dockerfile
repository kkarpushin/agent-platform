FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home app
COPY sdk ./sdk
ARG AGENT_NAME
COPY agents/${AGENT_NAME}/ ./agent/
USER app
CMD ["uvicorn", "agent:app", "--app-dir", "/app/agent", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]
