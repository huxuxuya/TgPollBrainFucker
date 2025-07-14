# Генерация таблицы рассадки для carpool
from src.shared.utils import generate_table

def generate_carpool_table(cars):
    """
    cars: список объектов Car (с атрибутами driver_id, seats, passengers, depart_time, depart_area)
    """
    headers = ["Водитель", "Места", "Пассажиры", "Время", "Район"]
    data = []
    for car in cars:
        data.append([
            car.driver_id,
            f"{len(car.passengers)}/{car.seats}",
            ", ".join(str(p.user_id) for p in car.passengers),
            car.depart_time,
            car.depart_area
        ])
    return generate_table(data, headers) 