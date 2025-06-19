import asyncio
import os
import json
import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.staticfiles import StaticFiles
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, TypeHandler
from telegram import Update
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import ProgrammingError

from src.config import BOT_TOKEN, logger, WEB_URL, DEV_MODE
from src.database import init_database, get_poll
from src.handlers import admin, dashboard, voting, text, results, misc, base, settings

# --- Database Schema Migration ---
def check_and_update_db_schema():
    """
    Connects to the database, inspects the 'poll_settings' table,
    and applies necessary alterations automatically. This makes the bot
    more robust to schema changes.
    """
    logger.info("Checking database schema...")
    POSTGRES_URL = os.environ.get('DATABASE_URL')

    if not POSTGRES_URL:
        logger.warning("DATABASE_URL not found, skipping schema check (assuming local SQLite).")
        return
        
    if not POSTGRES_URL.startswith('postgres'):
        logger.error("DATABASE_URL is not a PostgreSQL URL, skipping schema check.")
        return

    # Use 'postgresql' as the dialect name for SQLAlchemy
    if POSTGRES_URL.startswith('postgres://'):
        POSTGRES_URL = POSTGRES_URL.replace('postgres://', 'postgresql://', 1)

    try:
        engine = create_engine(POSTGRES_URL)
        inspector = inspect(engine)
        
        with engine.connect() as connection:
            
            TABLE_NAME = 'poll_settings'
            existing_columns = [col['name'] for col in inspector.get_columns(TABLE_NAME)]
            
            # --- Define desired columns and alterations ---
            COLUMNS_TO_ADD = {
                'show_results_after_vote': 'BOOLEAN DEFAULT TRUE',
                'show_heatmap': 'BOOLEAN NOT NULL DEFAULT TRUE'
            }
            COLUMNS_TO_ALTER = [
                ("default_show_names", "BOOLEAN", "SET DEFAULT TRUE", "USING CASE WHEN default_show_names=1 THEN TRUE ELSE FALSE END"),
                ("default_show_count", "BOOLEAN", "SET DEFAULT TRUE", "USING CASE WHEN default_show_count=1 THEN TRUE ELSE FALSE END")
            ]

            # --- Add new columns ---
            for column_name, column_type in COLUMNS_TO_ADD.items():
                if column_name not in existing_columns:
                    logger.info(f"Schema Update: Adding column '{column_name}' to '{TABLE_NAME}'...")
                    trans = connection.begin()
                    try:
                        connection.execute(text(f'ALTER TABLE {TABLE_NAME} ADD COLUMN {column_name} {column_type}'))
                        trans.commit()
                        logger.info(f"   Column '{column_name}' added successfully.")
                    except Exception as e:
                        logger.error(f"   !! ERROR adding column '{column_name}': {e}")
                        trans.rollback()

            # --- Alter existing columns (e.g., changing type) ---
            for col_name, col_type, col_default, col_using in COLUMNS_TO_ALTER:
                # This is a simplified check. A more robust system would inspect the type directly.
                # For now, we assume if it needs altering, the change hasn't run.
                try:
                    # Try to set the default first, which is safe.
                    trans = connection.begin()
                    connection.execute(text(f"ALTER TABLE {TABLE_NAME} ALTER COLUMN {col_name} {col_default}"))
                    connection.execute(text(f"ALTER TABLE {TABLE_NAME} ALTER COLUMN {col_name} TYPE {col_type} {col_using}"))
                    trans.commit()
                    logger.info(f"Schema Update: Successfully altered column '{col_name}'.")
                except ProgrammingError as e:
                    # If it fails with "column is already of type...", it's a non-issue.
                    if "already of type" in str(e):
                        logger.info(f"Schema Info: Column '{col_name}' is already of the correct type.")
                    else:
                        logger.error(f"Schema Update: Failed to alter column '{col_name}'. Error: {e}")
                    trans.rollback()

    except Exception as e:
        logger.error(f"An unexpected error occurred during schema check: {e}")
        return
        
    logger.info("Database schema check complete.")


# --- Web App Registry ---
BUNDLED_WEB_APPS = {}

def load_bundled_web_apps():
    """Scans the web_apps directory and loads their manifests and routes."""
    web_apps_dir = Path("src/web_apps")
    if not web_apps_dir.is_dir():
        return

    for app_dir in web_apps_dir.iterdir():
        if not app_dir.is_dir():
            continue
        
        manifest_path = app_dir / "manifest.json"
        router_path = app_dir / "router.py"
        
        if manifest_path.is_file() and router_path.is_file():
            try:
                with open(manifest_path, 'r', encoding='utf-8') as f:
                    manifest = json.load(f)
                
                app_id = manifest.get('id')
                if not app_id:
                    logger.warning(f"Skipping web app in '{app_dir.name}' due to missing 'id' in manifest.")
                    continue
                
                # Dynamically load the router module
                spec = importlib.util.spec_from_file_location(f"src.web_apps.{app_dir.name}.router", router_path)
                router_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(router_module)

                manifest['router'] = router_module.routes
                manifest['static_dir'] = app_dir / "static"
                
                BUNDLED_WEB_APPS[app_id] = manifest
                logger.info(f"Successfully loaded bundled web app: '{manifest.get('name')}' (ID: {app_id})")

            except Exception as e:
                logger.error(f"Failed to load web app from '{app_dir.name}': {e}", exc_info=True)


# --- PTB Application Setup ---
application = Application.builder().token(BOT_TOKEN).build()

# Register all handlers
application.add_handler(TypeHandler(Update, base.track_chats), group=-1)
application.add_handler(MessageHandler(filters.ChatType.GROUPS, base.register_user_activity), group=-2)
application.add_handler(CommandHandler("start", base.start))
application.add_handler(CommandHandler("help", base.help_command))
application.add_handler(CommandHandler("dashboard", dashboard.private_chat_entry_point))
application.add_handler(CommandHandler("done", text.done_command))
application.add_handler(CommandHandler("export_json", admin.export_json))
application.add_handler(CommandHandler("import_json", admin.import_json))
application.add_handler(CallbackQueryHandler(dashboard.dashboard_callback_handler, pattern="^dash:"))
application.add_handler(CallbackQueryHandler(voting.vote_callback_handler, pattern="^vote:"))
application.add_handler(CallbackQueryHandler(results.results_callback_handler, pattern="^results:"))
application.add_handler(CallbackQueryHandler(settings.settings_callback_handler, pattern="^settings:"))
application.add_handler(CallbackQueryHandler(base.unrecognized_button))
application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), text.text_handler))
application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, misc.web_app_data_handler))
application.add_handler(MessageHandler(filters.FORWARDED, misc.forwarded_message_handler))
application.add_error_handler(base.error_handler)


# --- Lifespan and Starlette Server Setup ---
@asynccontextmanager
async def lifespan(app: Starlette):
    """Handles bot startup and shutdown."""
    init_database()
    check_and_update_db_schema() # Check/update schema on startup
    load_bundled_web_apps()
    application.bot_data['BUNDLED_WEB_APPS'] = BUNDLED_WEB_APPS
    
    await application.initialize()
    await application.bot.set_webhook(url=f"{WEB_URL}/telegram", allowed_updates=Update.ALL_TYPES)
    logger.info("Bot initialized and webhook set.")
    yield
    logger.info("Server shutting down...")
    await application.shutdown()
    logger.info("Bot shut down.")


async def root(request: Request):
    """A simple root endpoint to confirm the server is running."""
    return PlainTextResponse("Web server is running.")

async def telegram_webhook(request: Request) -> JSONResponse:
    """Handles incoming Telegram updates by passing them to the application for direct processing."""
    update_data = await request.json()
    update = Update.de_json(data=update_data, bot=application.bot)
    await application.process_update(update)
    return JSONResponse({"ok": True})

# --- Dynamic Route Mounting ---
# We must load the apps *before* the routes are defined, so Starlette is aware of them.
load_bundled_web_apps()

routes = [
    Route("/", endpoint=root),
    Route("/telegram", endpoint=telegram_webhook, methods=["POST"]),
]

# Mount routes and static files for each bundled web app
for app_id, app_data in BUNDLED_WEB_APPS.items():
    # Mount the app-specific routes
    routes.append(Mount(f"/web_apps/{app_id}", routes=app_data['router'], name=f"webapp-{app_id}"))
    
    # Mount the static files directory if it exists
    static_dir = app_data.get('static_dir')
    if static_dir and static_dir.is_dir():
        routes.append(Mount(f"/web_apps/{app_id}/static", app=StaticFiles(directory=static_dir), name=f"webapp-static-{app_id}"))


server = Starlette(routes=routes, lifespan=lifespan)

async def main() -> None:
    """Starts the bot in polling mode for local development."""
    logger.info("Running in development mode (polling)...")
    init_database()
    check_and_update_db_schema() # Also check for dev mode
    load_bundled_web_apps() # Also load them for dev mode
    application.bot_data['BUNDLED_WEB_APPS'] = BUNDLED_WEB_APPS
    
    # Remove any existing webhook
    logger.info("Deleting webhook...")
    await application.bot.delete_webhook()
    
    # Start polling
    logger.info("Starting polling...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    if DEV_MODE:
        # The main() function handles loading apps for development polling mode.
        asyncio.run(main())
    else:
        # For production, Gunicorn will find the `server` object.
        # The top-level call to `load_bundled_web_apps()` ensures the routes are ready.
        logger.info("Running in production mode. This script should be run by an ASGI server like Gunicorn.") 