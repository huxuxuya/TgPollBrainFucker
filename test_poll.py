from src.database import engine, SessionLocal, Poll, PollSetting, Response, add_or_update_response
import logging
import random

logger = logging.getLogger(__name__)
logger.setLevel('DEBUG')

# Create a test poll
session = SessionLocal()
try:
    # Generate a unique poll_id
    poll_id = random.randint(10000, 99999)
    logger.info(f"Generated unique poll_id: {poll_id}")
    
    # Save poll_id to file for verification
    with open('test_poll_poll_id.txt', 'w') as f:
        f.write(str(poll_id))
    
    # Create test poll with new poll_id
    poll = Poll(
        poll_id=poll_id,
        chat_id=123,
        options="Option 1,Option 2,Option 3",
        status="active",
        poll_type="native"
    )
    
    # Create poll setting with multiple answers allowed
    poll_setting = PollSetting(
        poll_id=poll_id,
        allow_multiple_answers=True,
        show_results_after_vote=True,
        default_show_names=True,
        default_show_count=True
    )
    
    # Debug logging
    logger.info(f"Created poll with ID: {poll.poll_id}")
    logger.info(f"Poll setting allow_multiple_answers: {poll_setting.allow_multiple_answers}")
    
    # Add to session
    session.add(poll)
    session.add(poll_setting)
    session.commit()
    
    # Test multiple selection
    logger.info("\nTesting multiple selection...")
    
    # First vote
    logger.info("\nFirst vote for Option 1...")
    add_or_update_response(poll_id, 12345, 'Test', 'User', 'testuser', option_text='Option 1')
    
    # Second vote
    logger.info("\nSecond vote for Option 2...")
    add_or_update_response(poll_id, 12345, 'Test', 'User', 'testuser', option_text='Option 2')
    
    # Verify responses
    responses = session.query(Response).filter_by(poll_id=poll_id, user_id=12345).all()
    logger.info(f"\nResponses found: {len(responses)}")
    
    # Print each response
    for resp in responses:
        logger.info(f"Response: {resp.response}")
    
    # Commit the session to ensure responses are saved
    session.commit()
    for resp in responses:
        logger.info(f"Response: {resp.response}")
        
finally:
    session.close()
