# Docker контейнеризация TgPollBrainFucker

## Описание

Упрощенная Docker контейнеризация Telegram бота с использованием:
- SQLite базы данных
- Polling режима (без webhook)
- Существующих данных из репозитория

## Быстрый старт

### 1. Подготовка

```bash
# Клонирование репозитория
git clone <repository-url>
cd TgPollBrainFucker

# Создание директорий для данных
mkdir -p data logs

# Копирование конфигурации
cp env.example .env
# Отредактируйте .env файл с вашими данными
```

### 2. Запуск

```bash
# Сборка и запуск
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

## Конфигурация

### Переменные окружения

- `BOT_TOKEN` - токен Telegram бота
- `BOT_OWNER_ID` - ID владельца бота
- `DEV_MODE` - режим разработки (всегда true)
- `DATABASE_URL` - URL базы данных SQLite

### Volumes

- `./data:/app/data` - данные приложения
- `./logs:/app/logs` - логи
- `./poll_data.db:/app/poll_data.db` - база данных

## Управление

### Основные команды

```bash
# Запуск
docker-compose up -d

# Остановка
docker-compose down

# Перезапуск
docker-compose restart

# Просмотр логов
docker-compose logs -f

# Выполнение команд в контейнере
docker-compose exec pollbot bash
```

### Обновление

```bash
# Остановка
docker-compose down

# Обновление кода
git pull

# Пересборка и запуск
docker-compose up -d --build
```

## Структура данных

```
/app/
├── poll_data.db          # База данных SQLite
├── data/                 # Данные приложения
├── logs/                 # Логи
└── src/                  # Исходный код
```

## Безопасность

- Запуск от непривилегированного пользователя
- Данные и конфигурация в volumes
- Health checks для мониторинга

## Мониторинг

- Логи через `docker-compose logs -f`
- Health checks каждые 30 секунд
- Проверка доступности базы данных

## Резервное копирование

```bash
# Копирование базы данных
cp poll_data.db poll_data.db.backup

# Копирование всех данных
tar -czf backup.tar.gz poll_data.db data/ logs/
```

## Устранение проблем

### Проблемы с правами доступа

```bash
# Исправление прав
sudo chown -R $USER:$USER data/ logs/
```

### Проблемы с базой данных

```bash
# Проверка базы данных
docker-compose exec pollbot python -c "
import sqlite3
conn = sqlite3.connect('/app/poll_data.db')
print('Database is accessible')
conn.close()
"
```

### Проблемы с запуском

```bash
# Просмотр подробных логов
docker-compose logs --tail=100 pollbot

# Перезапуск с пересборкой
docker-compose down
docker-compose up -d --build
```

