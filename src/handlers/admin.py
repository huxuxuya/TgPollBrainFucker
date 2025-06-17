from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatAction
import os
from datetime import datetime
import json
import io
from sqlalchemy.orm import class_mapper

from src.config import DATABASE_PATH, logger
from src.decorators import admin_only
from src import database as db


def model_to_dict(obj):
    """Converts a SQLAlchemy object to a dictionary."""
    if obj is None:
        return None
    # Get column names and their values
    return {c.key: getattr(obj, c.key) for c in class_mapper(obj.__class__).columns}


@admin_only
async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends the database file to the user."""
    await update.message.reply_chat_action(ChatAction.UPLOAD_DOCUMENT)
    try:
        with open(DATABASE_PATH, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=f"poll_db_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
                caption="Here's your database backup."
            )
    except FileNotFoundError:
        await update.message.reply_text("Database file not found.")
    except Exception as e:
        await update.message.reply_text(f"An error occurred: {e}")


@admin_only
async def restore(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Restores the database from a file."""
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("Please reply to a message with a database file to restore.")
        return
        
    document = update.message.reply_to_message.document
    if not document.file_name.endswith('.db'):
        await update.message.reply_text("Please provide a valid .db file.")
        return

    try:
        db_file = await document.get_file()
        await db_file.download_to_drive(DATABASE_PATH)
        await update.message.reply_text("Database restored successfully. Please restart the bot for changes to take effect.")
    except Exception as e:
        await update.message.reply_text(f"An error occurred during restore: {e}")


@admin_only
async def export_json(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Exports all database data to a JSON file and sends it to the user."""
    await update.message.reply_text("Starting data export... This may take a moment.")
    await update.message.reply_chat_action(ChatAction.UPLOAD_DOCUMENT)

    session = db.SessionLocal()
    try:
        # Fetch all data from all tables
        full_data = {
            "users": [model_to_dict(u) for u in session.query(db.User).all()],
            "known_chats": [model_to_dict(kc) for kc in session.query(db.KnownChat).all()],
            "participants": [model_to_dict(p) for p in session.query(db.Participant).all()],
            "polls": [model_to_dict(p) for p in session.query(db.Poll).all()],
            "web_apps": [model_to_dict(wa) for wa in session.query(db.WebApp).all()],
            "responses": [model_to_dict(r) for r in session.query(db.Response).all()],
            "poll_settings": [model_to_dict(ps) for ps in session.query(db.PollSetting).all()],
            "poll_option_settings": [model_to_dict(pos) for pos in session.query(db.PollOptionSetting).all()],
        }

        # Convert data to JSON string
        json_string = json.dumps(full_data, indent=4, ensure_ascii=False)
        json_bytes = json_string.encode('utf-8')

        # Create an in-memory file
        bio = io.BytesIO(json_bytes)
        bio.name = f"tg_poll_bot_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        await update.message.reply_document(
            document=bio,
            filename=bio.name,
            caption="Here is your data export."
        )

    except Exception as e:
        await update.message.reply_text(f"An error occurred during export: {e}")
        logger.error(f"Export failed: {e}", exc_info=True)
    finally:
        session.close()


@admin_only
async def import_json(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Imports data from a JSON file, wiping all existing data."""
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("Please reply to a message with a .json export file to import.")
        return

    document = update.message.reply_to_message.document
    if not document.file_name.endswith('.json'):
        await update.message.reply_text("Please provide a valid .json file.")
        return

    await update.message.reply_text("Downloading and parsing file...")
    try:
        json_file = await document.get_file()
        json_bytes = await json_file.download_as_bytearray()
        data_to_import = json.loads(json_bytes.decode('utf-8'))
    except Exception as e:
        await update.message.reply_text(f"Failed to download or parse JSON file: {e}")
        return

    required_keys = ["users", "polls", "responses"]
    if not all(key in data_to_import for key in required_keys):
        await update.message.reply_text("The JSON file does not appear to be a valid export file.")
        return
        
    await update.message.reply_text("⚠️ **WARNING!** The entire database will be wiped before import. This cannot be undone.")

    session = db.SessionLocal()
    MODELS_IN_ORDER = [
        db.User, db.KnownChat, db.Participant, db.WebApp, db.Poll,
        db.Response, db.PollSetting, db.PollOptionSetting
    ]

    try:
        # 1. Wipe data in reverse order of dependencies
        for model in reversed(MODELS_IN_ORDER):
            session.query(model).delete(synchronize_session=False)
        await update.message.reply_text("Database wiped. Starting import...")

        # 2. Import data in order of dependencies
        for model in MODELS_IN_ORDER:
            table_name = model.__tablename__
            if table_name in data_to_import and data_to_import[table_name]:
                # Using bulk_insert_mappings for efficiency
                session.bulk_insert_mappings(model, data_to_import[table_name])

        session.commit()
        await update.message.reply_text("✅ Data imported successfully! It's recommended to restart the bot.")

    except Exception as e:
        session.rollback()
        await update.message.reply_text(f"An error occurred during import: {e}")
        logger.error(f"Import failed: {e}", exc_info=True)
    finally:
        session.close() 