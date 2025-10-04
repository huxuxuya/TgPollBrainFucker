# Сборка Docker образа на Synology NAS

## Подготовка Synology

### 1. Установка Docker Package

1. Откройте **Package Center** в DSM
2. Найдите и установите **Docker**
3. Запустите Docker из главного меню

### 2. Включение SSH (для способа 1)

1. Перейдите в **Control Panel** → **Terminal & SNMP**
2. Включите **Enable SSH service**
3. Запомните порт (обычно 22)

### 3. Создание директорий

Через **File Station** создайте структуру:
```
/volume1/docker/pollbot/
├── data/
├── logs/
└── poll_data.db (скопируйте из проекта)
```

## Способы сборки

### Способ 1: Через SSH (Рекомендуемый)

#### Подключение к Synology

```bash
# Подключение по SSH
ssh admin@YOUR_SYNOLOGY_IP

# Переход в директорию Docker
cd /volume1/docker/pollbot
```

#### Загрузка проекта

```bash
# Создание директории проекта
mkdir -p /volume1/docker/pollbot
cd /volume1/docker/pollbot

# Загрузка файлов проекта (выберите один способ):

# Вариант A: Через SCP с вашего компьютера
scp -r /path/to/TgPollBrainFucker/* admin@YOUR_SYNOLOGY_IP:/volume1/docker/pollbot/

# Вариант B: Через Git (если проект в репозитории)
git clone YOUR_REPOSITORY_URL .

# Вариант C: Через File Station (веб-интерфейс)
# Загрузите файлы через веб-интерфейс в /volume1/docker/pollbot/
```

#### Сборка и запуск

```bash
# Переход в директорию проекта
cd /volume1/docker/pollbot

# Создание .env файла
cat > .env << EOF
BOT_TOKEN=your_actual_bot_token_here
BOT_OWNER_ID=your_telegram_user_id_here
EOF

# Сборка образа
docker-compose -f docker-compose.synology.yml build

# Запуск контейнера
docker-compose -f docker-compose.synology.yml up -d

# Проверка статуса
docker-compose -f docker-compose.synology.yml ps

# Просмотр логов
docker-compose -f docker-compose.synology.yml logs -f
```

### Способ 2: Через веб-интерфейс Docker

#### Загрузка файлов

1. Откройте **File Station**
2. Перейдите в `/volume1/docker/pollbot/`
3. Загрузите все файлы проекта
4. Создайте `.env` файл с настройками

#### Сборка образа

1. Откройте **Docker** в DSM
2. Перейдите в **Image**
3. Нажмите **Add** → **Add from folder**
4. Выберите папку `/volume1/docker/pollbot/`
5. Нажмите **Next**
6. Введите имя образа: `pollbot`
7. Нажмите **Next** → **Apply**

#### Создание контейнера

1. В **Docker** перейдите в **Container**
2. Нажмите **Create**
3. Выберите образ `pollbot`
4. Нажмите **Next**
5. Настройте контейнер:
   - **Container name**: `pollbot`
   - **Enable auto-restart**: ✓
6. Нажмите **Advanced Settings**
7. В **Volume** добавьте:
   - `/volume1/docker/pollbot/data` → `/app/data`
   - `/volume1/docker/pollbot/logs` → `/app/logs`
   - `/volume1/docker/pollbot/poll_data.db` → `/app/poll_data.db`
8. В **Environment** добавьте:
   - `DEV_MODE=true`
   - `DATABASE_URL=sqlite:///app/poll_data.db`
   - `BOT_TOKEN=your_actual_bot_token_here`
   - `BOT_OWNER_ID=your_telegram_user_id_here`
9. Нажмите **Apply** → **Next** → **Apply**

### Способ 3: Локальная сборка + загрузка

#### Сборка на компьютере

```bash
# Сборка образа для ARM (если Synology на ARM)
docker buildx build --platform linux/arm64 -t pollbot:synology .

# Или для x86_64
docker buildx build --platform linux/amd64 -t pollbot:synology .

# Сохранение образа в файл
docker save pollbot:synology > pollbot-synology.tar
```

#### Загрузка на Synology

```bash
# Загрузка образа на Synology
scp pollbot-synology.tar admin@YOUR_SYNOLOGY_IP:/volume1/docker/

# Подключение к Synology
ssh admin@YOUR_SYNOLOGY_IP

# Загрузка образа в Docker
cd /volume1/docker
docker load < pollbot-synology.tar

# Создание контейнера
docker run -d \
  --name pollbot \
  --restart unless-stopped \
  -v /volume1/docker/pollbot/data:/app/data \
  -v /volume1/docker/pollbot/logs:/app/logs \
  -v /volume1/docker/pollbot/poll_data.db:/app/poll_data.db \
  -e DEV_MODE=true \
  -e DATABASE_URL=sqlite:///app/poll_data.db \
  -e BOT_TOKEN=your_actual_bot_token_here \
  -e BOT_OWNER_ID=your_telegram_user_id_here \
  pollbot:synology
```

## Управление контейнером

### Через SSH

```bash
# Просмотр статуса
docker ps

# Просмотр логов
docker logs pollbot

# Остановка
docker stop pollbot

# Запуск
docker start pollbot

# Перезапуск
docker restart pollbot

# Удаление
docker rm pollbot
```

### Через веб-интерфейс

1. Откройте **Docker** в DSM
2. Перейдите в **Container**
3. Найдите контейнер `pollbot`
4. Используйте кнопки управления

## Обновление

### Через SSH

```bash
cd /volume1/docker/pollbot

# Остановка контейнера
docker-compose -f docker-compose.synology.yml down

# Обновление кода
git pull  # или загрузите новые файлы

# Пересборка
docker-compose -f docker-compose.synology.yml build

# Запуск
docker-compose -f docker-compose.synology.yml up -d
```

## Мониторинг

### Просмотр логов

```bash
# Через SSH
docker logs -f pollbot

# Через веб-интерфейс
# Docker → Container → pollbot → Details → Log
```

### Проверка здоровья

```bash
# Проверка статуса контейнера
docker ps

# Проверка использования ресурсов
docker stats pollbot
```

## Устранение проблем

### Проблемы с правами доступа

```bash
# Исправление прав на Synology
sudo chown -R 1026:100 /volume1/docker/pollbot
sudo chmod -R 755 /volume1/docker/pollbot
```

### Проблемы с архитектурой

```bash
# Проверка архитектуры Synology
uname -m

# Сборка для правильной архитектуры
docker buildx build --platform linux/$(uname -m) -t pollbot:synology .
```

### Проблемы с сетью

```bash
# Проверка сетевых настроек
docker network ls
docker network inspect bridge
```

## Безопасность

### Рекомендации

1. **Используйте сильные пароли** для SSH
2. **Ограничьте SSH доступ** по IP
3. **Регулярно обновляйте** DSM и Docker
4. **Делайте резервные копии** данных
5. **Мониторьте логи** на предмет подозрительной активности

### Firewall

1. Откройте **Control Panel** → **Security** → **Firewall**
2. Создайте правило для Docker (порт 2376)
3. Ограничьте доступ только необходимым IP

## Резервное копирование

### Автоматическое резервное копирование

```bash
# Создание скрипта резервного копирования
cat > /volume1/docker/pollbot/backup.sh << 'EOF'
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/volume1/docker/pollbot/backups"

mkdir -p $BACKUP_DIR

# Копирование базы данных
cp /volume1/docker/pollbot/poll_data.db $BACKUP_DIR/poll_data_$DATE.db

# Копирование данных
tar -czf $BACKUP_DIR/data_$DATE.tar.gz /volume1/docker/pollbot/data

# Удаление старых бэкапов (старше 30 дней)
find $BACKUP_DIR -name "*.db" -mtime +30 -delete
find $BACKUP_DIR -name "*.tar.gz" -mtime +30 -delete

echo "Backup completed: $DATE"
EOF

chmod +x /volume1/docker/pollbot/backup.sh

# Добавление в cron (ежедневно в 2:00)
echo "0 2 * * * /volume1/docker/pollbot/backup.sh" | crontab -
```

## Производительность

### Оптимизация для Synology

1. **Используйте SSD** для Docker volumes
2. **Ограничьте ресурсы** контейнера
3. **Мониторьте использование** CPU и RAM
4. **Настройте логирование** для экономии места

### Ограничение ресурсов

```yaml
# В docker-compose.synology.yml добавьте:
services:
  pollbot:
    # ... существующие настройки ...
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.5'
          memory: 256M
```

Теперь у вас есть полная инструкция для развертывания бота на Synology NAS!

