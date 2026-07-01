from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/ritual")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Onboarding / profile
    goals = Column(Text, default="")           # e.g. "build muscle, lose weight"
    equipment = Column(Text, default="")       # e.g. "dumbbells, resistance bands"
    workout_days = Column(String, default="")  # e.g. "Mon,Wed,Fri"
    workout_duration = Column(Integer, default=45)  # minutes
    dietary_prefs = Column(Text, default="")   # e.g. "vegetarian, no dairy"
    weekly_grocery_budget = Column(Float, default=0.0)
    onboarded = Column(Boolean, default=False)

    # Workout video preferences (set once, reused on every generation)
    use_videos = Column(Boolean, default=False)
    video_days = Column(Integer, default=0)
    video_types = Column(Text, default="")
    weekly_goal = Column(Text, default="")

    # Daily habit targets
    sleep_goal_hours = Column(Float, default=8.0)
    water_goal_oz = Column(Float, default=64.0)


class DailyLog(Base):
    __tablename__ = "daily_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    date = Column(Date, nullable=False)
    sleep_hours = Column(Float, nullable=True)
    stress_level = Column(Integer, nullable=True)   # 1-5
    energy_level = Column(Integer, nullable=True)   # 1-5
    mood = Column(Integer, nullable=True)            # 1-5
    water_oz = Column(Float, nullable=True)          # ounces of water
    period = Column(Boolean, default=False)
    notes = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    plan_text = Column(Text, nullable=False)
    week_start = Column(Date, nullable=True)


class MealPlan(Base):
    __tablename__ = "meal_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    plan_text = Column(Text, nullable=False)
    grocery_list = Column(Text, nullable=False)
    budget = Column(Float, nullable=True)

    # Saved context, so single-day regeneration can reuse the same settings
    food_prefs = Column(Text, default="")
    macro_prefs = Column(Text, default="")
    show_macros = Column(Boolean, default=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)