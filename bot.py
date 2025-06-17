import asyncio
import os
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import PlainTextResponse, JSONResponse
from starlette.templating import Jinja2Templates
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, TypeHandler
from telegram import Update

from src.config import BOT_TOKEN, logger, WEB_URL, DEV_MODE
from src.database import init_database, get_poll
from src.handlers import admin, dashboard, voting, text, results, misc, base, settings

# --- PTB Application Setup ---
application = Application.builder().token(BOT_TOKEN).build()

# Register all handlers
application.add_handler(TypeHandler(Update, base.track_chats), group=-1)
application.add_handler(CommandHandler("start", base.start))
application.add_handler(CommandHandler("help", base.help_command))
application.add_handler(CommandHandler("dashboard", dashboard.private_chat_entry_point))
application.add_handler(CommandHandler("done", text.done_command))
application.add_handler(CommandHandler("backup", admin.backup))
application.add_handler(CommandHandler("restore", admin.restore))
application.add_handler(CallbackQueryHandler(dashboard.dashboard_callback_handler, pattern="^dash:"))
application.add_handler(CallbackQueryHandler(voting.vote_callback_handler, pattern="^vote:"))
application.add_handler(CallbackQueryHandler(results.results_callback_handler, pattern="^res:"))
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
    await application.initialize()
    await application.bot.set_webhook(url=f"{WEB_URL}/telegram", allowed_updates=Update.ALL_TYPES)
    logger.info("Bot initialized and webhook set.")
    yield
    logger.info("Server shutting down...")
    await application.shutdown()
    logger.info("Bot shut down.")

templates = Jinja2Templates(directory="templates")

async def root(request: Request):
    """A simple root endpoint to confirm the server is running."""
    return PlainTextResponse("Web server is running.")

async def vote_page(request: Request):
    """Serves the voting page for a specific poll."""
    poll_id = request.path_params['poll_id']
    poll = get_poll(poll_id)
    if not poll:
        return PlainTextResponse("Poll not found", status_code=404)
    
    options = [opt.strip() for opt in poll.options.split(',')]
    
    context = {
        "request": request,
        "poll_title": poll.message, 
        "poll_options": options, 
        "poll_id": poll.poll_id
    }
    return templates.TemplateResponse("vote.html", context)

async def telegram_webhook(request: Request) -> JSONResponse:
    """Handles incoming Telegram updates by passing them to the application for direct processing."""
    update_data = await request.json()
    update = Update.de_json(data=update_data, bot=application.bot)
    await application.process_update(update)
    return JSONResponse({"ok": True})

routes = [
    Route("/", endpoint=root),
    Route("/vote/{poll_id:int}", endpoint=vote_page),
    Route("/telegram", endpoint=telegram_webhook, methods=["POST"]),
]

server = Starlette(routes=routes, lifespan=lifespan)

# No need for a __main__ block anymore, gunicorn handles the launch.
async def main() -> None:
    """Starts the bot in polling mode for local development."""
    logger.info("Running in development mode (polling)...")
    init_database()
    
    # Remove any existing webhook
    logger.info("Deleting webhook...")
    await application.bot.delete_webhook()
    
    # Start polling
    logger.info("Starting polling...")
    await application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    if DEV_MODE:
        asyncio.run(main())
    else:
        logger.warning("Running in production mode. This script should be run by an ASGI server like Gunicorn, not directly.") 