from datetime import datetime
from sqlalchemy import (
    Column, String, Float, Integer, DateTime, Boolean, JSON, ForeignKey
)
from sqlalchemy.orm import relationship
from app.db import Base

class Station(Base):
    __tablename__ = "stations"
    station_id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    agency = Column(String, nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    active_status = Column(DateTime, default=datetime.utcnow)

    raw_readings = relationship("RawReading",back_populates="station")
    cleaned_readings = relationship("CleanedReading", back_populates="station")
    aqi_records = relationship("StationAQI", back_populates="station")

class RawReading(Base):
    __tablename__ = "raw_readings"
    id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(String, ForeignKey("stations.station_id"), nullable=False)
    min_value = Column(Float, nullable=True)  
    max_value = Column(Float, nullable=True)
    avg_value = Column(Float, nullable=True)
    timestamp = Column(DateTime, nullable=False)  
    ingested_at = Column(DateTime, default=datetime.utcnow)

    station = relationship("Station", back_populates="raw_readings")

class CleanedReading(Base):
    __tablename__ = "cleaned_readings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(String, ForeignKey("stations.station_id"), nullable=False)
    pollutant_id = Column(String, nullable=False)
    min_value = Column(Float, nullable=True)
    max_value = Column(Float, nullable=True)
    avg_value = Column(Float, nullable=True)
    timestamp = Column(DateTime, nullable=False)
    ingested_at = Column(DateTime, default=datetime.utcnow)
    is_corrected = Column(Boolean, default=False)
    correction_reason = Column(String, nullable=True)

    station = relationship("Station", back_populates="cleaned_readings")

class StationAQI(Base):
    __tablename__ = "station_aqi"

    id = Column(Integer, primary_key=True, autoincrement=True)
    station_id = Column(String, ForeignKey("stations.station_id"), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    aqi_value = Column(Integer, nullable=True)  
    status = Column(String, nullable=False)  
    category = Column(String, nullable=True)  
    dominant_pollutant = Column(String, nullable=True)
    sub_indices = Column(JSON, nullable=True)  
    reason = Column(String, nullable=True)  

    station = relationship("Station", back_populates="aqi_records")

class WardBoundary(Base):
    __tablename__ = "ward_boundaries"

    ward_id = Column(String, primary_key = True)
    ward_name = Column(String, nullable=False)
    geometry = Column(JSON, nullable=False)

class WardPopulation(Base):
    __tablename__ = "ward_population"

    ward_id = Column(String, ForeignKey("ward_boundaries.ward_id"), primary_key=True)
    population = Column(Integer, nullable=False)
    census_year = Column(Integer, nullable=False)
