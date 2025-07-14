from sqlalchemy import Column, Integer, String, ForeignKey
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