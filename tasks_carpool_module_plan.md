# Детальный план реализации модуля рассадки по машинам (carpool) для Telegram-бота

## 1. Архитектурные принципы

- **Модульность:** Вся логика carpool находится в отдельной папке-модуле, не смешивается с ядром.
- **Интеграция через интерфейс:** Ядро бота взаимодействует с модулем через чётко определённый API (например, через реестр типов опросов).
- **Расширяемость:** В будущем можно добавить другие модули по аналогии.

## 2. Структура файлов

```
src/
  modules/
    carpool/
      __init__.py
      carpool.py         # Точка входа, регистрация обработчиков
      handlers.py        # Все обработчики команд, callback, диалогов
      models.py          # Модели машин, пассажиров, связи с опросом
      display.py         # Генерация таблицы рассадки
      utils.py           # Вспомогательные функции
      tests/
        test_carpool.py
```

## 3. Этапы реализации

### 1. Проектирование интерфейса интеграции

- В ядре (например, в voting.py) реализовать “реестр типов опросов”:
  ```python
  POLL_TYPE_HANDLERS = {
      "native": native_poll_handler,
      "carpool": carpool_poll_handler,  # импортируется из модуля
      # ...
  }
  ```
- При создании/обработке опроса ядро делегирует всю логику соответствующему обработчику.

### 2. Создание модуля carpool

- В `carpool.py` реализовать функцию регистрации обработчиков:
  ```python
  def register_handlers(application):
      # application — объект бота/диспетчера
      application.add_handler(...)  # все carpool-обработчики
  ```
- В `handlers.py` реализовать:
  - Обработку запуска опроса carpool
  - Диалоги с водителем (личка)
  - Обработку выбора машины пассажиром
  - Динамическое обновление вариантов
  - Визуализацию рассадки

- В `models.py`:
  - Модель Car (id, водитель, места, время, район, пассажиры)
  - Модель связи Car <-> Poll

- В `display.py`:
  - Генерация таблицы рассадки (аналогично тепловой карте)

- В `utils.py`:
  - Вспомогательные функции (например, поиск свободных мест, форматирование времени и т.д.)

### 3. Интеграция с ядром

- В `src/bot.py` или `src/handlers/voting.py`:
  - При инициализации бота импортировать и вызвать `register_handlers` из carpool.
  - В обработчиках опросов добавить делегирование по типу опроса.

### 4. Миграции и модели

- Если требуется новая таблица (Car, CarPassenger), добавить модели в carpool/models.py.
- Добавить миграцию Alembic для новых таблиц.

### 5. Тестирование

- В `modules/carpool/tests/` реализовать тесты для всех ключевых сценариев:
  - Создание машины
  - Диалоги с водителем
  - Выбор машины пассажиром
  - Генерация таблицы рассадки

### 6. Документация

- Описать интерфейс между ядром и модулем (какие функции должен реализовать модуль, как регистрировать обработчики).
- Описать структуру моделей и миграций.

## 4. Детализация шагов

### Шаг 1. Создать папку и файлы модуля

- `mkdir -p src/modules/carpool/tests`
- Создать пустые файлы: `__init__.py`, `carpool.py`, `handlers.py`, `models.py`, `display.py`, `utils.py`, `tests/test_carpool.py`

### Шаг 2. Реализовать модели

- В `models.py`:
  ```python
  from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
  from sqlalchemy.orm import relationship
  from src.database import Base

  class Car(Base):
      __tablename__ = "carpool_cars"
      id = Column(Integer, primary_key=True)
      poll_id = Column(Integer, ForeignKey("polls.poll_id"))
      driver_id = Column(Integer)
      seats = Column(Integer)
      depart_time = Column(String)
      depart_area = Column(String)
      passengers = relationship("CarPassenger", back_populates="car")

  class CarPassenger(Base):
      __tablename__ = "carpool_passengers"
      id = Column(Integer, primary_key=True)
      car_id = Column(Integer, ForeignKey("carpool_cars.id"))
      user_id = Column(Integer)
      car = relationship("Car", back_populates="passengers")
  ```

### Шаг 3. Реализовать обработчики

- В `handlers.py`:
  - Обработчик запуска опроса carpool
  - Обработчик “Я водитель” (диалог в личке)
  - Обработчик выбора машины пассажиром
  - Обновление вариантов и рассадки

### Шаг 4. Реализовать генерацию таблицы

- В `display.py`:
  - Функция для генерации картинки рассадки по аналогии с тепловой картой

### Шаг 5. Интеграция с ядром

- В `carpool.py`:
  ```python
  from .handlers import register_carpool_handlers

  def register_handlers(application):
      register_carpool_handlers(application)
  ```
- В ядре:
  ```python
  from modules.carpool import register_handlers as register_carpool_handlers
  register_carpool_handlers(application)
  ```

### Шаг 6. Миграции

- Создать миграцию Alembic для новых таблиц.

### Шаг 7. Тесты

- В `tests/test_carpool.py` — тесты на все ключевые сценарии.

## 5. Пример реестра типов опросов

```python
# src/handlers/voting.py
from modules.carpool.handlers import handle_carpool_poll

POLL_TYPE_HANDLERS = {
    "native": handle_native_poll,
    "carpool": handle_carpool_poll,
}

def handle_poll(update, context, poll_type, ...):
    handler = POLL_TYPE_HANDLERS.get(poll_type)
    if handler:
        return handler(update, context, ...)
    else:
        # fallback
```

## 6. Потенциальные сложности

- Согласование интерфейса между ядром и модулем (какие данные и события передавать).
- Миграции БД (не забыть про alembic revision).
- Тестирование асинхронных диалогов и обновлений вариантов.

## 7. Чек-лист задач

- [ ] Создать структуру модуля carpool
- [ ] Реализовать модели машин и пассажиров
- [ ] Реализовать обработчики carpool-опроса
- [ ] Реализовать генерацию таблицы рассадки
- [ ] Интегрировать модуль с ядром через реестр типов опросов
- [ ] Добавить миграцию Alembic
- [ ] Написать тесты для модуля
- [ ] Обновить документацию

