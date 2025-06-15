# Text and wizard handlers
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text.text_handler))
application.add_handler(CommandHandler("done", text.done_command))

# Forwarded message handler
application.add_handler(MessageHandler(filters.FORWARDED, misc.forwarded_message_handler))

# Web App data handler
application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, misc.web_app_data_handler))

# Catch-all for other button presses not caught by specific handlers
application.add_handler(CallbackQueryHandler(base.unrecognized_button))

# Error handler 