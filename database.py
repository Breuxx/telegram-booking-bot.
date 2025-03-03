from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()

class Attendance(Base):
    __tablename__ = 'attendance'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False)
    username = Column(String, nullable=False)
    action = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(engine)

def log_action(user_id, username, action):
    with Session() as session:
        record = Attendance(user_id=user_id, username=username, action=action)
        session.add(record)
        session.commit()

def get_user_stats(user_id):
    with Session() as session:
        return session.query(Attendance).filter_by(user_id=user_id).all()
