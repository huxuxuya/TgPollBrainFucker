import asyncio
import os
from flask import Flask, render_template, request
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler, TypeHandler
from telegram import Update

from src.config import BOT_TOKEN, logger, WEB_URL
from src.database import init_database, get_poll
from src.handlers import admin, dashboard, voting, text, results, misc, base, settings

# --- Initialize Application and Handlers ---
# Create the Application and pass it your bot's token.
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


# --- Initialize Flask Server ---
server = Flask(__name__)

@server.route("/")
def root():
    """A simple root endpoint to confirm the server is running."""
    return "Web server is running."

@server.route("/vote/<int:poll_id>")
def vote_page(poll_id: int):
    """Serves the voting page for a specific poll."""
    poll = get_poll(poll_id)
    if not poll:
        return "Poll not found", 404
    
    options = [opt.strip() for opt in poll.options.split(',')]
    
    return render_template(
        "vote.html", 
        poll_title=poll.message, 
        poll_options=options, 
        poll_id=poll.poll_id
    )

@server.post("/telegram")
async def telegram() -> str:
    """Handles incoming Telegram updates by passing them to the application."""
    await application.update_queue.put(Update.de_json(data=request.get_json(force=True), bot=application.bot))
    return "OK"

async def setup():
    """Initializes the bot and sets the webhook."""
    # Initialize the database
    init_database()
    
    # We need to run the bot in a separate task
    await application.bot.set_webhook(url=f"{WEB_URL}/telegram", allowed_updates=Update.ALL_TYPES)
    
    # The Flask server will be run by Gunicorn, not here.
    # We just need to ensure the bot is ready.
    # We use initialize() instead of start() to not block.
    await application.initialize()


# The main entry point is now running the `setup` async function
if __name__ == "__main__":
    asyncio.run(setup()) 