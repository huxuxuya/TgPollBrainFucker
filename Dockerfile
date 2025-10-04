# Базовый образ Python
FROM python:3.11-slim

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Создание пользователя для безопасности
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Создание рабочих директорий
RUN mkdir -p /app/data /app/logs
WORKDIR /app

# Копирование кода приложения
COPY . .

# Установка Python зависимостей (только для бота)
RUN pip install --no-cache-dir \
    python-telegram-bot==20.8 \
    python-dotenv==1.0.0 \
    SQLAlchemy==2.0.25 \
    Pillow==10.3.0 \
    starlette==0.37.2 \
    uvicorn==0.23.2 \
    gunicorn==21.2.0 \
    jinja2==3.1.3 \
    aiofiles==23.2.1

# Точка входа
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Установка прав доступа
RUN chown -R appuser:appuser /app
RUN chmod o+w /app
USER appuser

# Переменные окружения
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV DEV_MODE=true

ENTRYPOINT ["/entrypoint.sh"]
