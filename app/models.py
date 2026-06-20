import datetime
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base

class BenchmarkRun(Base):
    __tablename__ = "benchmark_runs"

    id = Column(String, primary_key=True, index=True)
    status = Column(String, default="PENDING")  # PENDING, RUNNING, COMPLETED, FAILED
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    error_message = Column(String, nullable=True)
    depot_name = Column(String, nullable=False)
    depot_lat = Column(Float, nullable=False)
    depot_lon = Column(Float, nullable=False)
    stops_count = Column(Integer, default=0)
    stops_data = Column(Text, nullable=True)  # JSON serialized input stops

    results = relationship("BenchmarkResult", back_populates="run", cascade="all, delete-orphan")
    quantum_jobs = relationship("QuantumJob", back_populates="run", cascade="all, delete-orphan")


class QuantumJob(Base):
    __tablename__ = "quantum_jobs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_id = Column(String, ForeignKey("benchmark_runs.id"), nullable=False)
    job_id = Column(String, nullable=False, index=True)
    algorithm = Column(String, nullable=False)  # QAOA, QAI_HOBO
    backend_name = Column(String, nullable=False)
    status = Column(String, default="SUBMITTED")  # SUBMITTED, COMPLETED, FAILED
    qpu_time_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    run = relationship("BenchmarkRun", back_populates="quantum_jobs")


class BenchmarkResult(Base):
    __tablename__ = "benchmark_results"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    run_id = Column(String, ForeignKey("benchmark_runs.id"), nullable=False)
    algorithm = Column(String, nullable=False)  # OR-Tools, QAOA, QAI_HOBO
    tour = Column(Text, nullable=False)  # JSON serialized list of route indices
    distance_meters = Column(Float, nullable=False)
    is_valid = Column(Boolean, default=True)
    validation_error = Column(String, nullable=True)
    approximation_ratio = Column(Float, nullable=True)  # Relative to OR-Tools (quantum_dist / ort_dist)
    execution_time_ms = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    run = relationship("BenchmarkRun", back_populates="results")
