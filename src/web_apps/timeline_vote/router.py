from starlette.routing import Route, Mount
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.templating import Jinja2Templates
from pathlib import Path

from src.database import get_poll, get_response, get_user_name, SessionLocal

# Setup templates
templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))

async def get_poll_data(request: Request):
    """API endpoint to fetch poll data."""
    try:
        poll_id = int(request.query_params.get('poll_id'))
        user_id = int(request.query_params.get('user_id'))
    except (TypeError, ValueError):
        return JSONResponse({'error': 'Invalid poll_id or user_id'}, status_code=400)

    poll = get_poll(poll_id)
    if not poll:
        return JSONResponse({'error': 'Poll not found'}, status_code=404)

    # Find out what this specific user voted for, if anything
    session = SessionLocal()
    user_response = None
    try:
        response_obj = get_response(poll_id, user_id)
        if response_obj:
            user_response = response_obj.response
    finally:
        session.close()

    return JSONResponse({
        'title': poll.message,
        'poll_id': poll.poll_id,
        'user_vote': user_response
    })

async def timeline_vote_view(request: Request):
    """Serves the main HTML view for the timeline voting app."""
    return templates.TemplateResponse(
        "view.html",
        {"request": request}
    )

routes = [
    Route("/", endpoint=timeline_vote_view),
    Route("/api/poll", endpoint=get_poll_data),
] 