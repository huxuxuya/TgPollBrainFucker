import os
import logging
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, Boolean, Float, Text, PrimaryKeyConstraint, ForeignKey, inspect, text, UniqueConstraint, event, select
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship, Mapped
from typing import Union, List, Optional, Set
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
    poll_id: Mapped[int] = Column(Integer, primary_key=True)
    chat_id: Mapped[int] = Column(Integer, nullable=False)
    message_id: Mapped[Optional[int]] = Column(Integer)
    photo_file_id: Mapped[Optional[str]] = Column(String) # For storing the file_id of the heatmap image
    message: Mapped[Optional[str]] = Column(String)
    options: Mapped[Optional[str]] = Column(String)
    status: Mapped[str] = Column(String, default='draft') # draft, active, closed
    poll_type = Column(String, default='native', nullable=False)
    web_app_id = Column(String, nullable=True)
    nudge_message_id = Column(BigInteger)
    
    # This relationship allows us to easily access responses via poll.responses
    responses = relationship("Response", backref="poll", cascade="all, delete-orphan")

class Response(Base):
    __tablename__ = 'responses'
    poll_id = Column(Integer, ForeignKey('polls.poll_id'), primary_key=True)
    user_id = Column(BigInteger, primary_key=True)
    response = Column(Text, primary_key=True)

class PollSetting(Base):
    __tablename__ = 'poll_settings'
    poll_id = Column(Integer, primary_key=True)
    allow_multiple_answers = Column(Boolean, default=False)
    show_results_after_vote = Column(Boolean, default=True)
    default_show_names = Column(Boolean, default=True)
    default_show_count = Column(Boolean, default=True)
    show_heatmap = Column(Boolean, default=True, nullable=False)
    default_names_style = Column(String, default='list')
    target_sum = Column(Float, default=0)
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

# --- Новая таблица: исключения участников для конкретного опроса ----------
class PollExclusion(Base):
    """Содержит пары (poll_id, user_id) для участников, исключённых только из
    данного опроса. Если записи нет, участник считается включённым.
    """
    __tablename__ = 'poll_exclusions'
    poll_id = Column(Integer, primary_key=True)
    user_id = Column(BigInteger, primary_key=True)


# --- Database migrations ---
# The manual run_migrations() function has been removed.
# All schema changes are now handled by Alembic to ensure consistency.

# Initialize database connection
def init_database():
    """
    Initializes the database. Alembic is now the single source of truth for migrations,
    so manual migration and table creation logic has been removed.
    The deployment process should run 'alembic upgrade head' to apply migrations.
    """
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

def add_or_update_response_ext(session: Session, poll_id: int, user_id: int, first_name: str, last_name: str, username: str, option_index: int = None, option_text: str = None):
    """
    Adds or updates a user's response to a poll using an EXISTING session.
    This is the core logic.
    """
    # First, ensure the user exists in the main Users table
    user = session.query(User).filter_by(user_id=user_id).first()
    if not user:
        user = User(user_id=user_id, first_name=first_name, last_name=last_name, username=username)
        session.add(user)
    else: # Update user's name if it has changed
        user.first_name = first_name
        user.last_name = last_name
        user.username = username
    
    poll = session.query(Poll).filter_by(poll_id=poll_id).first()
    poll_setting = session.query(PollSetting).filter_by(poll_id=poll_id).first()
    if not poll:
        logger.error(f"Poll with ID {poll_id} not found, can't add response.")
        return
    
    # Debug logging for multiple answers setting
    logger.info(f"[DEBUG] Poll ID {poll_id} multiple answers setting: {poll_setting.allow_multiple_answers if poll_setting else 'No setting found'}")

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

    allow_multiple = poll_setting.allow_multiple_answers if poll_setting else False

    if allow_multiple:
        # For multiple choice, check if this specific response exists and toggle it
        response = session.query(Response).filter_by(poll_id=poll_id, user_id=user_id, response=response_value).first()
        if response:
            # User is un-voting for this option
            session.delete(response)
        else:
            # User is voting for a new option
            new_response = Response(poll_id=poll_id, user_id=user_id, response=response_value)
            session.add(new_response)
    else:
        # For single choice, remove all previous responses for this user in this poll
        session.query(Response).filter_by(poll_id=poll_id, user_id=user_id).delete()
        # And add the new one
        new_response = Response(poll_id=poll_id, user_id=user_id, response=response_value)
        session.add(new_response)

def add_or_update_response(poll_id: int, user_id: int, first_name: str, last_name: str, username: str, option_index: int = None, option_text: str = None):
    """
    Public-facing function that creates a session and calls the core logic.
    """
    session = SessionLocal()
    try:
        add_or_update_response_ext(
            session=session,
            poll_id=poll_id,
            user_id=user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            option_index=option_index,
            option_text=option_text
        )
        session.commit()
    except Exception as e:
        logger.error(f"Exception in add_or_update_response: {e}", exc_info=True)
        session.rollback()
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
def get_poll(poll_id: int, session: Optional[Session] = None):
    """Fetches a poll by its ID, optionally using an existing session."""
    manage_session = not session
    if manage_session:
        session = SessionLocal()
    
    try:
        poll = session.query(Poll).filter_by(poll_id=poll_id).first()
        return poll
    finally:
        if manage_session:
            session.close()

def get_responses(poll_id: int, session: Optional[Session] = None) -> List[Response]:
    """Fetches all responses for a poll, optionally using an existing session."""
    manage_session = not session
    if manage_session:
        session = SessionLocal()
    
    try:
        responses = session.query(Response).filter_by(poll_id=poll_id).all()
        return responses
    finally:
        if manage_session:
            session.close()

def get_poll_setting(poll_id: int, create: bool = False, session: Optional[Session] = None) -> Optional[PollSetting]:
    """Retrieves settings for a specific poll."""
    manage_session = not session
    if manage_session:
        session = SessionLocal()
    
    try:
        setting = session.query(PollSetting).filter_by(poll_id=poll_id).first()
        if not setting and create:
            setting = PollSetting(poll_id=poll_id)
            session.add(setting)
            # We need to commit here if we created it, so the calling function can use it.
            # A flush might be sufficient, but commit is safer for cross-function use.
            if manage_session:
                session.commit()
            else:
                # If we are in a managed session, just flush to get the ID
                session.flush()
        return setting
    finally:
        if manage_session:
            session.close()

def get_poll_option_setting(poll_id: int, option_index: int, create: bool = False) -> Union[PollOptionSetting, None]:
    session = SessionLocal()
    try:
        setting = session.query(PollOptionSetting).filter_by(poll_id=poll_id, option_index=option_index).first()
        if not setting and create:
            setting = PollOptionSetting(poll_id=poll_id, option_index=option_index)
            session.add(setting)
            # Commit to persist, then refresh to make sure attributes are loaded
            session.commit()
        if setting is not None:
            # Ensure all scalar attributes are loaded and detach from session to avoid DetachedInstanceError
            session.refresh(setting)
            session.expunge(setting)
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

def get_participants(chat_id: int, session: Optional[Session] = None):
    """Fetches all participants for a given chat."""
    manage_session = not session
    if manage_session:
        session = SessionLocal()
    
    try:
        participants = session.query(Participant).filter_by(chat_id=chat_id).all()
        return participants
    finally:
        if manage_session:
            session.close()

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

def add_poll(poll: Poll) -> int:
    """Adds a poll to the database and returns its new ID."""
    session = SessionLocal()
    session.add(poll)
    session.commit()
    poll_id = poll.poll_id
    session.close()
    return poll_id

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

# --- Utility helpers -------------------------------------------------------

def commit_session(*instances):
    """Commits changes for the given ORM instances in a fresh session.

    Поскольку во многих обработчиках мы получаем объекты через функции, которые
    внутри себя уже закрывают сессию, объекты становятся "detached". Чтобы всё
    же сохранить модификации, мы создаём новую сессию, `merge`-им переданные
    экземпляры и фиксируем изменения.

    Использование:

        poll.nudge_message_id = 123
        db.commit_session(poll)

    Если объекты не переданы, функция просто делает `commit()` пустой сессии –
    это безопасно, но ни на что не влияет.
    """
    session = SessionLocal()
    try:
        for obj in instances:
            if obj is not None:
                session.merge(obj)
        session.commit()
    except Exception as e:
        logger.error(f"Error in commit_session: {e}")
        session.rollback()
        raise
    finally:
        session.close()

def get_poll_exclusions(poll_id: int, session: Optional[Session] = None) -> Set[int]:
    """Возвращает набор user_id, исключённых из данного опроса."""
    manage_session = session is None
    if manage_session:
        session = SessionLocal()
    try:
        rows = session.query(PollExclusion.user_id).filter_by(poll_id=poll_id).all()
        return {r.user_id for r in rows}
    finally:
        if manage_session:
            session.close()

def toggle_poll_exclusion(poll_id: int, user_id: int):
    """Переключает статус исключения пользователя для опроса."""
    session = SessionLocal()
    try:
        row = session.query(PollExclusion).filter_by(poll_id=poll_id, user_id=user_id).first()
        if row:
            session.delete(row)
            excluded = False
        else:
            session.add(PollExclusion(poll_id=poll_id, user_id=user_id))
            excluded = True
        session.commit()
        return excluded
    except Exception as e:
        logger.error(f"Error toggling poll exclusion: {e}")
        session.rollback()
        raise
    finally:
        session.close() 