# Вспомогательные функции для carpool

def find_free_seats(cars):
    """Вернуть список машин с доступными местами."""
    return [car for car in cars if len(car.passengers) < car.seats]

def format_time(timestr):
    """Форматировать время для отображения (заглушка)."""
    return timestr  # TODO: реализовать красивое форматирование

def validate_driver(driver_id):
    # Простейшая валидация водителя
    return driver_id is not None

def validate_passenger(user_id):
    # Простейшая валидация пассажира
    return user_id is not None 