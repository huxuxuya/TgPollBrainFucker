import os
import logging
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Boolean, Float, Text, PrimaryKeyConstraint, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from typing import Union, List
from telegram.helpers import escape_markdown

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
engine_args = {}
if DATABASE_URL.startswith('sqlite'):
    engine_args['connect_args'] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

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
    type = Column(String)

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
    poll_type = Column(String, default='native', nullable=False)
    message_id = Column(BigInteger)
    nudge_message_id = Column(BigInteger)
    
    # This relationship allows us to easily access responses via poll.responses
    responses = relationship("Response", backref="poll", cascade="all, delete-orphan")

class WebApp(Base):
    __tablename__ = 'web_apps'
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(BigInteger, nullable=False)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)

class Response(Base):
    __tablename__ = 'responses'
    poll_id = Column(Integer, ForeignKey('polls.poll_id'), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)
    response = Column(Text)

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
    poll_id = Column(Integer, primary_key=True)
    option_index = Column(Integer, primary_key=True)
    show_names = Column(Integer)
    names_style = Column(String)
    is_priority = Column(Integer, default=0)
    contribution_amount = Column(Float, default=0)
    emoji = Column(String)
    show_count = Column(Integer)
    show_contribution = Column(Integer, default=1)


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


def update_user(session: Session, user_id: int, first_name: str, last_name: str, username: str = None):
    """Creates or updates a user in the database using a provided session."""
    user = session.query(User).filter_by(user_id=user_id).first()
    if user:
        if first_name: user.first_name = first_name
        if last_name: user.last_name = last_name
        if username: user.username = username
    else:
        user = User(user_id=user_id, first_name=first_name, last_name=last_name, username=username)
        session.add(user)

def add_or_update_response(poll_id: int, user_id: int, first_name: str, last_name: str, username: str, option_index: int = None, option_text: str = None):
    """Adds or updates a user's response to a poll."""
    session = SessionLocal()
    try:
        # First, ensure the user exists in the main Users table
        user = session.query(User).filter_by(user_id=user_id).first()
        if not user:
            user = User(user_id=user_id, first_name=first_name, last_name=last_name, username=username)
            session.add(user)
            # We don't commit here, we let the response addition commit everything
        
        poll = session.query(Poll).filter_by(poll_id=poll_id).first()
        if not poll:
            logger.error(f"Poll with ID {poll_id} not found, can't add response.")
            return

        # Determine the response text
        response_value = None
        if option_text is not None:
            response_value = option_text
        elif option_index is not None:
            try:
                options = poll.options.split(',')
                response_value = options[option_index].strip()
            except IndexError:
                logger.error(f"Invalid option index {option_index} for poll {poll_id}")
                return
        else:
            logger.error("Either option_index or option_text must be provided.")
            return

        response = session.query(Response).filter_by(poll_id=poll_id, user_id=user_id).first()
        if response:
            response.response = response_value
        else:
            response = Response(poll_id=poll_id, user_id=user_id, response=response_value)
            session.add(response)
        
        session.commit()
    finally:
        session.close()

def add_user_to_participants(chat_id: int, user_id: int, username: str, first_name: str, last_name: str):
    """Adds a user and a participant entry in a single transaction."""
    session = SessionLocal()
    try:
        update_user(session, user_id, first_name, last_name, username)
        
        participant = session.query(Participant).filter_by(chat_id=chat_id, user_id=user_id).first()
        if not participant:
            participant = Participant(chat_id=chat_id, user_id=user_id, username=username, first_name=first_name, last_name=last_name)
            session.add(participant)
        
        session.commit()
    except Exception as e:
        logger.error(f"Error in add_user_to_participants: {e}")
        session.rollback()
    finally:
        session.close()

def update_user_standalone(user_id: int, first_name: str, last_name: str, username: str = None):
    """Standalone version of update_user for contexts without an existing session."""
    session = SessionLocal()
    try:
        update_user(session, user_id, first_name, last_name, username)
        session.commit()
    except Exception as e:
        logger.error(f"Error in update_user_standalone: {e}")
        session.rollback()
    finally:
        session.close()

def update_known_chats(chat_id: int, title: str, chat_type: str) -> None:
    """Обновление списка известных чатов"""
    session = SessionLocal()
    try:
        chat = session.query(KnownChat).filter_by(chat_id=chat_id).first()
        if chat:
            chat.title = title
            chat.type = chat_type
        else:
            chat = KnownChat(chat_id=chat_id, title=title, type=chat_type)
            session.add(chat)
        session.commit()
    except Exception as e:
        logger.error(f"Error updating known chats: {e}")
        session.rollback()
    finally:
        session.close()


def get_group_title(chat_id: int) -> str:
    """Получение названия группы"""
    session = SessionLocal()
    try:
        chat = session.query(KnownChat).filter_by(chat_id=chat_id).first()
        return chat.title if chat and chat.title else f"Группа {chat_id}"
    except Exception as e:
        logger.error(f"Error getting group title: {e}")
        return f"Группа {chat_id}"
    finally:
        session.close()


def get_user_name(session: Session, user_id: int, markdown_link: bool = False) -> str:
    """Gets a user's name from a given session, optionally formatted for Markdown."""
    logger.info(f"[DEBUG_GET_USER_NAME] Attempting to find user_id '{user_id}' in table '{User.__tablename__}'.")
    all_user_ids_in_db = [u.user_id for u in session.query(User.user_id).all()]
    logger.info(f"[DEBUG_GET_USER_NAME] Current user_ids in '{User.__tablename__}' table: {all_user_ids_in_db}")
    
    user = session.query(User).filter_by(user_id=user_id).first()

    # If user not found in 'users', try to find them in 'participants' and create the 'users' entry.
    if not user:
        logger.warning(f"User {user_id} not found in 'users' table. Checking 'participants' as a fallback.")
        participant = session.query(Participant).filter_by(user_id=user_id).first()
        if participant:
            logger.info(f"User {user_id} found in 'participants'. Creating entry in 'users' to self-heal.")
            user = User(
                user_id=participant.user_id,
                username=participant.username,
                first_name=participant.first_name,
                last_name=participant.last_name
            )
            session.add(user)
            # The calling function is responsible for the commit.

    # If user is not in our database, we can't create a pretty name, but we can still create a link.
    if not user:
        logger.info(f"[DEBUG_GET_USER_NAME] User {user_id} not found in DB.")
        if markdown_link:
            # Escape "User <id>" just in case, though it's safe.
            safe_name = escape_markdown(f"User {user_id}", version=2)
            return f"[{safe_name}](tg://user?id={user_id})"
        return f"User {user_id}"
    
    logger.info(f"[DEBUG_GET_USER_NAME] User {user_id} found in DB: {user.first_name}")

    # Construct the name from available details.
    name = user.first_name or ""
    if user.last_name:
        name = f"{name} {user.last_name}".strip()
    
    # Fallback to username if no name is available.
    if not name:
        name = user.username or f"User {user_id}"

    # Escape the name for Markdown and create the link if requested.
    if markdown_link:
        # Only use characters that are safe for Markdown links
        safe_name = escape_markdown(name, version=2)
        return f"[{safe_name}](tg://user?id={user_id})"
    
    return name

# Functions to fetch data for display logic
def get_poll(poll_id: int):
    session = SessionLocal()
    poll = session.query(Poll).filter_by(poll_id=poll_id).first()
    session.close()
    return poll

def get_responses(poll_id: int) -> List[Response]:
    session = SessionLocal()
    responses = session.query(Response).filter_by(poll_id=poll_id).all()
    session.close()
    return responses

def get_poll_setting(poll_id: int, create: bool = False) -> Union[PollSetting, None]:
    session = SessionLocal()
    try:
        setting = session.query(PollSetting).filter_by(poll_id=poll_id).first()
        if not setting and create:
            setting = PollSetting(poll_id=poll_id)
            session.add(setting)
            session.commit()
        return setting
    finally:
        session.close()

def get_poll_option_setting(poll_id: int, option_index: int, create: bool = False) -> Union[PollOptionSetting, None]:
    session = SessionLocal()
    try:
        setting = session.query(PollOptionSetting).filter_by(poll_id=poll_id, option_index=option_index).first()
        if not setting and create:
            setting = PollOptionSetting(poll_id=poll_id, option_index=option_index)
            session.add(setting)
            session.commit()
        return setting
    finally:
        session.close()


def get_known_chats():
    session = SessionLocal()
    chats = session.query(KnownChat).all()
    session.close()
    return chats

def get_polls_by_status(chat_id: int, status: str):
    session = SessionLocal()
    polls = session.query(Poll).filter_by(chat_id=chat_id, status=status).all()
    session.close()
    return polls

def get_participants(chat_id: int):
    session = SessionLocal()
    participants = session.query(Participant).filter_by(chat_id=chat_id).all()
    session.close()
    return participants

def get_participant(chat_id: int, user_id: int):
    session = SessionLocal()
    participant = session.query(Participant).filter_by(chat_id=chat_id, user_id=user_id).first()
    session.close()
    return participant

def get_response(poll_id: int, user_id: int):
    session = SessionLocal()
    response = session.query(Response).filter_by(poll_id=poll_id, user_id=user_id).first()
    session.close()
    return response

def add_poll(poll: Poll):
    session = SessionLocal()
    session.add(poll)
    session.commit()
    session.close()

def add_response(response: Response):
    session = SessionLocal()
    session.add(response)
    session.commit()
    session.close()

def add_participant(participant: Participant):
    session = SessionLocal()
    session.add(participant)
    session.commit()
    session.close()

def add_poll_setting(setting: PollSetting):
    session = SessionLocal()
    session.add(setting)
    session.commit()
    session.close()

def add_poll_option_setting(setting: PollOptionSetting):
    session = SessionLocal()
    session.add(setting)
    session.commit()
    session.close()

def delete_response(response: Response):
    session = SessionLocal()
    session.delete(response)
    session.commit()
    session.close()

def delete_poll(poll: Poll):
    session = SessionLocal()
    session.delete(poll)
    session.commit()
    session.close()

def delete_participants(chat_id: int):
    session = SessionLocal()
    try:
        session.query(Participant).filter_by(chat_id=chat_id).delete()
        session.commit()
    except Exception as e:
        logger.error(f"Error deleting participants for chat {chat_id}: {e}")
        session.rollback()
    finally:
        session.close()

def delete_responses_for_poll(poll_id: int):
    session = SessionLocal()
    try:
        session.query(Response).filter_by(poll_id=poll_id).delete()
        session.commit()
    except Exception as e:
        logger.error(f"Error deleting responses for poll {poll_id}: {e}")
        session.rollback()
    finally:
        session.close()

def delete_poll_setting(poll_id: int):
    session = SessionLocal()
    try:
        session.query(PollSetting).filter_by(poll_id=poll_id).delete()
        session.commit()
    except Exception as e:
        logger.error(f"Error deleting poll setting for poll {poll_id}: {e}")
        session.rollback()
    finally:
        session.close()

def delete_poll_option_settings(poll_id: int):
    session = SessionLocal()
    try:
        session.query(PollOptionSetting).filter_by(poll_id=poll_id).delete()
        session.commit()
    except Exception as e:
        logger.error(f"Error deleting poll option settings for poll {poll_id}: {e}")
        session.rollback()
    finally:
        session.close()

def get_web_apps(chat_id: int) -> List[WebApp]:
    """Fetches all registered web apps for a given chat."""
    session = SessionLocal()
    try:
        return session.query(WebApp).filter_by(chat_id=chat_id).order_by(WebApp.name).all()
    finally:
        session.close()

def add_web_app(chat_id: int, name: str, url: str):
    """Adds a new web app to the database."""
    session = SessionLocal()
    try:
        new_app = WebApp(chat_id=chat_id, name=name, url=url)
        session.add(new_app)
        session.commit()
    except Exception as e:
        logger.error(f"Error adding web app: {e}")
        session.rollback()
    finally:
        session.close()

def delete_web_app(app_id: int):
    """Deletes a web app by its ID."""
    session = SessionLocal()
    try:
        app_to_delete = session.query(WebApp).filter_by(id=app_id).first()
        if app_to_delete:
            session.delete(app_to_delete)
            session.commit()
            logger.info(f"Deleted Web App with ID {app_id}")
    finally:
        session.close()

def has_user_created_poll_in_chat(user_id: int, chat_id: int) -> bool:
    """
    Checks if a given user has ever created a poll in a specific chat.
    This is used as a fallback authorization method for non-visible admins.
    Note: This check assumes that the creator of a poll is the first person who voted.
    A more robust solution would be to add a 'creator_id' to the Polls table.
    """
    session = SessionLocal()
    try:
        # A user has "created" a poll if they have a response for it.
        # This is an approximation. For a more robust check, a `creator_id`
        # should be added to the Poll model.
        count = (
            session.query(Response)
            .join(Poll, Poll.poll_id == Response.poll_id)
            .filter(Poll.chat_id == chat_id, Response.user_id == user_id)
            .count()
        )
        return count > 0
    finally:
        session.close() 