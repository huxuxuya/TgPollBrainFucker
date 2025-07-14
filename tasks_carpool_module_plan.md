# Детальный план реализации модуля рассадки по машинам (carpool) для Telegram-бота (расширенная версия)

## 1. Архитектурные принципы

- **Модульность:** Вся логика carpool находится в отдельной папке-модуле, не смешивается с ядром.
- **Интерфейс плагина:** Каждый модуль реализует формальный интерфейс (PollModuleBase), ядро автоматически обнаруживает и регистрирует модули.
- **Общие утилиты:** Общие функции (генерация таблиц, диалоги, валидация) вынесены в shared/utils.py и доступны всем модулям.
- **Интеграция через интерфейс:** Ядро бота взаимодействует с модулем через API (реестр типов опросов или автопоиск).
- **Расширяемость:** В будущем можно добавить другие модули по аналогии.

## 2. Структура файлов

```
src/
  modules/
    base.py                # Базовый интерфейс PollModuleBase
    carpool/
      __init__.py
      carpool.py           # Класс CarpoolModule (реализация интерфейса)
      handlers.py          # Все обработчики команд, callback, диалогов
      models.py            # Модели машин, пассажиров, связи с опросом
      display.py           # Генерация таблицы рассадки
      utils.py             # Вспомогательные функции модуля
      tests/
        test_carpool.py
  shared/
    utils.py               # Общие функции для всех модулей (генерация таблиц, диалоги и т.д.)
```

## 3. Этапы реализации

### 1. Проектирование интерфейса плагина

- В `modules/base.py` реализовать абстрактный класс PollModuleBase:
  ```python
  class PollModuleBase:
      poll_type: str
      display_name: str
      def register_handlers(self, application): ...
      def get_poll_type(self): ...
      def get_display_name(self): ...
  ```
- Каждый модуль реализует этот интерфейс (например, CarpoolModule).

### 2. Автоматическая регистрация модулей

- В ядре (например, в bot.py) реализовать функцию автопоиска и регистрации всех модулей:
  ```python
  import importlib, pkgutil
  from modules.base import PollModuleBase

  def discover_and_register_modules(application):
      for _, module_name, _ in pkgutil.iter_modules(['src/modules']):
          module = importlib.import_module(f"modules.{module_name}.carpool")
          for attr in dir(module):
              obj = getattr(module, attr)
              if isinstance(obj, type) and issubclass(obj, PollModuleBase) and obj is not PollModuleBase:
                  poll_module = obj()
                  poll_module.register_handlers(application)
  ```

### 3. Создание модуля carpool

- В `carpool.py` реализовать класс CarpoolModule(PollModuleBase):
  - poll_type = "carpool"
  - display_name = "Рассадка по машинам"
  - register_handlers — регистрация всех carpool-обработчиков

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
  - Генерация таблицы рассадки (аналогично тепловой карте, с использованием shared/utils)

- В `utils.py`:
  - Вспомогательные функции (например, поиск свободных мест, форматирование времени и т.д.)

### 4. Общие утилиты

- В `shared/utils.py`:
  - Генерация таблиц (универсальная функция для разных модулей)
  - Диалоги с пользователем (универсальные шаблоны)
  - Валидация и парсинг пользовательских данных

### 5. Интеграция с ядром

- В `src/bot.py`:
  - При инициализации бота вызвать discover_and_register_modules(application)
  - В обработчиках опросов добавить делегирование по poll_type через интерфейс модуля

### 6. Миграции и модели

- Если требуется новая таблица (Car, CarPassenger), добавить модели в carpool/models.py.
- Добавить миграцию Alembic для новых таблиц.

### 7. Тестирование

- В `modules/carpool/tests/` реализовать тесты для всех ключевых сценариев:
  - Создание машины
  - Диалоги с водителем
  - Выбор машины пассажиром
  - Генерация таблицы рассадки

### 8. Документация

- Описать интерфейс между ядром и модулем (какие методы реализует PollModuleBase, как регистрировать обработчики).
- Описать структуру моделей и миграций.
- README по созданию и подключению новых модулей.

## 4. Детализация шагов

### Шаг 1. Создать структуру папок и файлов

- `mkdir -p src/modules/carpool/tests`
- `mkdir -p src/shared`
- Создать файлы: `base.py`, `carpool.py`, `handlers.py`, `models.py`, `display.py`, `utils.py`, `tests/test_carpool.py`, `shared/utils.py`

### Шаг 2. Реализовать интерфейс PollModuleBase

- В `modules/base.py`:
  ```python
  class PollModuleBase:
      poll_type: str
      display_name: str
      def register_handlers(self, application): ...
      def get_poll_type(self): ...
      def get_display_name(self): ...
  ```

### Шаг 3. Реализовать CarpoolModule

- В `carpool.py`:
  ```python
  from modules.base import PollModuleBase
  class CarpoolModule(PollModuleBase):
      poll_type = "carpool"
      display_name = "Рассадка по машинам"
      def register_handlers(self, application): ...
  ```

### Шаг 4. Реализовать обработчики и модели

- В `handlers.py`:
  - Обработчик запуска опроса carpool
  - Диалоги с водителем (личка)
  - Обработчик выбора машины пассажиром
  - Обновление вариантов и рассадки
- В `models.py`:
  - Модель Car
  - Модель CarPassenger

### Шаг 5. Реализовать общие утилиты

- В `shared/utils.py`:
  - Универсальная генерация таблиц (для carpool и других модулей)
  - Универсальные диалоги (например, ask_user_input, confirm_action)
  - Валидация и парсинг пользовательских данных

### Шаг 6. Интеграция с ядром

- В `src/bot.py`:
  - Вызвать discover_and_register_modules(application)
  - Делегировать обработку опроса через интерфейс модуля

### Шаг 7. Миграции

- Создать миграцию Alembic для новых таблиц.

### Шаг 8. Тесты

- В `tests/test_carpool.py` — тесты на все ключевые сценарии.

## 5. Пример интерфейса и автопоиска модулей

```python
# src/modules/base.py
class PollModuleBase:
    poll_type: str
    display_name: str
    def register_handlers(self, application): ...
    def get_poll_type(self): ...
    def get_display_name(self): ...

# src/modules/carpool/carpool.py
from modules.base import PollModuleBase
class CarpoolModule(PollModuleBase):
    poll_type = "carpool"
    display_name = "Рассадка по машинам"
    def register_handlers(self, application): ...

# src/bot.py
import importlib, pkgutil
from modules.base import PollModuleBase

def discover_and_register_modules(application):
    for _, module_name, _ in pkgutil.iter_modules(['src/modules']):
        module = importlib.import_module(f"modules.{module_name}.carpool")
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, PollModuleBase) and obj is not PollModuleBase:
                poll_module = obj()
                poll_module.register_handlers(application)
```

## 6. Потенциальные сложности

- Согласование интерфейса между ядром и модулем (какие методы и события передавать).
- Миграции БД (не забыть про alembic revision).
- Тестирование асинхронных диалогов и обновлений вариантов.
- Поддержка обратной совместимости при добавлении новых модулей.

## 7. Чек-лист задач

- [x] Создать структуру модуля carpool и shared/utils
- [x] Реализовать интерфейс PollModuleBase
- [x] Реализовать CarpoolModule
- [x] Модульная интеграция с ядром через автопоиск
- [x] Динамическое меню выбора типа опроса (wizard)
- [x] Модульные wizard-сценарии: создание carpool-опроса, публикация сообщения с deep-link-кнопкой
- [ ] Реализовать обработчики carpool-опроса для пассажиров (выбор машины, запись в машину)
- [ ] Реализовать генерацию и отображение таблицы рассадки (с использованием shared/utils)
- [ ] Реализовать общие и модульные утилиты (shared/utils.py, utils.py)
- [ ] Добавить миграцию Alembic для carpool-моделей
- [ ] Написать тесты для модуля (создание машин, рассадка, генерация таблицы)
- [ ] Обновить документацию (README, описание интерфейса, примеры)

---

Причины, почему команда /carpool не срабатывает в личке с ботом:

1. **Обработчик зарегистрирован, но фильтры не позволяют ловить команду в личке.**
2. **Возможно, бот не перезапущен после добавления нового обработчика.**
3. **Возможно, бот не видит команду, если она отправляется не в том чате (например, фильтр только для групп).**
4. **Возможно, есть ошибка в логике регистрации обработчиков или в автопоиске модулей.**
5. **Возможно, команда /carpool не доходит до нужного обработчика из-за порядка регистрации.**

---

### Диагностика

1. **Проверьте, что бот перезапущен после изменений.**
2. **Проверьте, что команда /carpool не конфликтует с другими обработчиками.**
3. **Проверьте, что в логе старта бота нет ошибок регистрации carpool-модуля.**
4. **Добавьте print/log в функцию carpool_start, чтобы убедиться, что она вызывается.**
5. **Проверьте, что обработчик CommandHandler("carpool", ...) не ограничен фильтрами (например, filters.ChatType.GROUPS).**

---

### Что можно сделать прямо сейчас

1. **Добавьте логирование в carpool_start:**
```python
import logging
async def carpool_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logging.warning("carpool_start вызван")
    if update.message:
        await update.message.reply_text("[carpool] Опрос рассадки по машинам: заглушка. Здесь будет запуск логики carpool.")
    else:
        logging.warning("update.message is None")
```

2. **Перезапустите бота и попробуйте снова.**
3. **Проверьте консоль/логи — появляется ли сообщение “carpool_start вызван”.**

---

### Если не помогает

- Проверьте, что discover_and_register_modules действительно вызывается до всех других add_handler.
- Проверьте, что нет других CommandHandler("carpool", ...) в проекте.
- Проверьте, что команда /carpool отправляется именно тому боту, который сейчас запущен.

---

Если после этих шагов всё равно не работает — пришлите логи запуска бота и/или вывод консоли после отправки команды /carpool.  
Я помогу локализовать и устранить причину!

