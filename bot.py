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

from src.config import BOT_TOKEN, logger, WEB_URL, DEV_MODE
from src.database import init_database, get_poll
from src.handlers import admin, dashboard, voting, text, results, misc, base, settings

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