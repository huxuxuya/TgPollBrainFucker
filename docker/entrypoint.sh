#!/bin/bash
set -e

# Функция для инициализации
init_app() {
    echo "Initializing TgPollBrainFucker..."
    
    # Создание директорий если не существуют
    mkdir -p /app/data /app/logs
    
    # Проверка существования базы данных
    if [ ! -f "/app/poll_data.db" ]; then
        echo "Warning: poll_data.db not found. Creating empty database..."
        # Создание пустой базы данных если не существует
        python -c "
from src.database import init_database
init_database()
print('Database initialized.')
"
    else
        echo "Using existing database: poll_data.db"
    fi
    
    echo "Application initialization complete."
}

# Функция для запуска приложения
start_app() {
    echo "Starting bot in polling mode..."
    python bot.py
}

# Основная логика
main() {
    echo "Starting TgPollBrainFucker..."
    
    # Инициализация
    init_app
    
    # Запуск приложения
    start_app
}

# Обработка сигналов для graceful shutdown
trap 'echo "Received shutdown signal"; exit 0' SIGTERM SIGINT

# Запуск основной функции
main "$@"

