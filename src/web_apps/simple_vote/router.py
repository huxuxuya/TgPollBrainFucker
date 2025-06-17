from starlette.routing import Route
from starlette.requests import Request
from starlette.templating import Jinja2Templates

from src.database import get_poll

# Each web app can have its own templates
templates = Jinja2Templates(directory="src/web_apps/simple_vote/templates")

async def view_page(request: Request):
    """Serves the main page for this web app."""
    # We get poll_id from a query parameter
    poll_id = request.query_params.get('poll_id')
    
    # It's crucial to validate and handle cases where poll_id is missing or invalid
    if not poll_id:
        return templates.TemplateResponse("error.html", {"request": request, "error_message": "Poll ID is missing."})

    poll = get_poll(int(poll_id))
    if not poll:
        return templates.TemplateResponse("error.html", {"request": request, "error_message": "Poll not found."})
    
    options = [opt.strip() for opt in poll.options.split(',')]
    
    context = {
        "request": request,
        "poll_title": poll.message, 
        "poll_options": options, 
        "poll_id": poll.poll_id
    }
    return templates.TemplateResponse("view.html", context)

# Define the routes for this specific web app
routes = [
    Route("/", endpoint=view_page),
] 