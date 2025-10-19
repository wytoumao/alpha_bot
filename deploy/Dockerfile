FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY pyproject.toml README.md ./
COPY collector ./collector
COPY notifier ./notifier
COPY config ./config
COPY deploy ./deploy
COPY tests ./tests
COPY .gitignore ./.gitignore

RUN pip install --upgrade pip && \
    pip install . && \
    playwright install chromium

ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Taipei

CMD ["python", "-m", "collector.alpha_watch"]
