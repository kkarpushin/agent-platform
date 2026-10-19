FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock && useradd --uid 10001 --create-home app
COPY platform ./platform
COPY config ./config
COPY knowledge ./knowledge
COPY agents ./agents
COPY skills ./skills
COPY processes ./processes
COPY sdk ./sdk
COPY tests ./tests
USER app
CMD ["uvicorn", "app:app", "--app-dir", "/app/platform", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
