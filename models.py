# models.py
from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean, ForeignKey
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, nullable=False, unique=True)
    first_name = Column(String)
    username = Column(String)
    is_blocked = Column(Boolean, default=False)
    captcha_code = Column(String)
    captcha_expiration = Column(DateTime)
    last_action = Column(DateTime)
    applications = relationship('Application', back_populates='user')

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"

class Application(Base):
    __tablename__ = 'applications'

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    crypto_type = Column(String, nullable=False)
    amount = Column(Float, nullable=False)  # Количество криптовалюты
    amount_rub = Column(Float, nullable=False)  # Сумма в RUB
    wallet_address = Column(String, nullable=False)
    payment_method = Column(String, nullable=False)
    crypto_rub_rate = Column(Float, nullable=False)  # Курс обмена на момент создания
    status = Column(String, default='pending')  # Статус заявки
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship('User', back_populates='applications')

    def __repr__(self):
        return (f"<Application(id={self.id}, user_id={self.user_id}, crypto_type='{self.crypto_type}', "
                f"amount={self.amount}, amount_rub={self.amount_rub}, status='{self.status}')>")
    
class Commission(Base):
    __tablename__ = 'commission'

    id = Column(Integer, primary_key=True)
    rate = Column(Float, default=2.5)
    updated_at = Column(DateTime, default=datetime.utcnow)

class PaymentDetails(Base):
    __tablename__ = 'payment_details'

    id = Column(Integer, primary_key=True)
    bank_name = Column(String, nullable=False)
    card_number = Column(String, nullable=False, unique=True)
    recipient_name = Column(String, nullable=False)  
    added_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return (f"<PaymentDetails(id={self.id}, bank_name='{self.bank_name}', "
                f"card_number='{self.card_number}', recipient_name='{self.recipient_name}')>")


class ActionLog(Base):
    __tablename__ = 'action_logs'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=True)
    action = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

class AdminActionLog(Base):
    __tablename__ = 'admin_action_logs'

    id = Column(Integer, primary_key=True)
    admin_id = Column(Integer, nullable=False)
    action = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return (f"<AdminActionLog(id={self.id}, admin_id={self.admin_id}, "
                f"action='{self.action}', timestamp={self.timestamp})>")
