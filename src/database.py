import os
import logging
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Boolean, Float, Text, PrimaryKeyConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

# Определение базы для моделей
Base = declarative_base()

# Получение строки подключения из переменных окружения
# По умолчанию используется SQLite, если не указан DATABASE_URL для PostgreSQL
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///poll_data.db')
if DATABASE_URL.startswith('postgres'):
    # Для render.com может потребоваться замена 'postgres://' на 'postgresql://'
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
logger.info(f"Using database: {DATABASE_URL}")

# Создание движка и сессии
engine = create_engine(DATABASE_URL, echo=False)
Session = sessionmaker(bind=engine)
session = Session()

# Модели таблиц
class User(Base):
    __tablename__ = 'users'
    user_id = Column(BigInteger, primary_key=True)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)

class KnownChat(Base):
    __tablename__ = 'known_chats'
    chat_id = Column(BigInteger, primary_key=True)
    title = Column(String)

class Participant(Base):
    __tablename__ = 'participants'
    chat_id = Column(BigInteger)
    user_id = Column(BigInteger)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    excluded = Column(Integer, default=0)
    __table_args__ = (PrimaryKeyConstraint('chat_id', 'user_id'),)

class Poll(Base):
    __tablename__ = 'polls'
    poll_id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger)
    message = Column(Text)
    options = Column(Text)
    status = Column(String, default='draft')
    message_id = Column(BigInteger)
    nudge_message_id = Column(BigInteger)

class Response(Base):
    __tablename__ = 'responses'
    poll_id = Column(Integer)
    user_id = Column(BigInteger)
    response = Column(Text)
    __table_args__ = (PrimaryKeyConstraint('poll_id', 'user_id'),)

class PollSetting(Base):
    __tablename__ = 'poll_settings'
    poll_id = Column(Integer, primary_key=True)
    default_show_names = Column(Integer, default=1)
    default_names_style = Column(String, default='list')
    target_sum = Column(Float, default=0)
    default_show_count = Column(Integer, default=1)
    nudge_negative_emoji = Column(String, default='❌')

class PollOptionSetting(Base):
    __tablename__ = 'poll_option_settings'
    poll_id = Column(Integer)
    option_index = Column(Integer)
    show_names = Column(Integer)
    names_style = Column(String)
    is_priority = Column(Integer, default=0)
    contribution_amount = Column(Float, default=0)
    emoji = Column(String)
    show_count = Column(Integer)
    show_contribution = Column(Integer, default=1)
    __table_args__ = (PrimaryKeyConstraint('poll_id', 'option_index'),)


def init_database():
    """Инициализация структуры базы данных"""
    try:
        Base.metadata.create_all(engine)
        logger.info("Database initialized with required tables.")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        raise


def run_migration():
    """Запуск миграции базы данных, если требуется"""
    # Здесь можно добавить миграцию данных, если нужно
    pass


def add_user_to_participants(chat_id: int, user_id: int, username: str, first_name: str, last_name: str) -> None:
    """Добавление пользователя в список участников"""
    try:
        # Добавление или обновление пользователя
        user = session.query(User).filter_by(user_id=user_id).first()
        if user:
            user.username = username
            user.first_name = first_name
            user.last_name = last_name
        else:
            user = User(user_id=user_id, username=username, first_name=first_name, last_name=last_name)
            session.add(user)

        # Добавление или обновление участника
        participant = session.query(Participant).filter_by(chat_id=chat_id, user_id=user_id).first()
        if participant:
            participant.username = username
            participant.first_name = first_name
            participant.last_name = last_name
        else:
            participant = Participant(chat_id=chat_id, user_id=user_id, username=username, first_name=first_name, last_name=last_name)
            session.add(participant)

        session.commit()
    except Exception as e:
        logger.error(f"Error adding user to participants: {e}")
        session.rollback()


def update_known_chats(chat_id: int, title: str) -> None:
    """Обновление списка известных чатов"""
    try:
        chat = session.query(KnownChat).filter_by(chat_id=chat_id).first()
        if chat:
            chat.title = title
        else:
            chat = KnownChat(chat_id=chat_id, title=title)
            session.add(chat)
        session.commit()
    except Exception as e:
        logger.error(f"Error updating known chats: {e}")
        session.rollback()


def get_group_title(chat_id: int) -> str:
    """Получение названия группы"""
    try:
        chat = session.query(KnownChat).filter_by(chat_id=chat_id).first()
        return chat.title if chat and chat.title else f"Группа {chat_id}"
    except Exception as e:
        logger.error(f"Error getting group title: {e}")
        return f"Группа {chat_id}"


def get_user_name(user_id: int, markdown_link: bool = False) -> str:
    """Получение имени пользователя"""
    try:
        user = session.query(User).filter_by(user_id=user_id).first()
        if not user:
            return f"User{user_id}"
        name = user.first_name or ''
        if user.last_name:
            name += f" {user.last_name}"
        name = name.strip()
        if not name:
            name = user.username or f"User{user_id}"
        if markdown_link and user.username:
            return f"[{name}](tg://user?id={user_id})"
        return name
    except Exception as e:
        logger.error(f"Error getting user name: {e}")
        return f"User{user_id}" 