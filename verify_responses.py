from src.database import engine, SessionLocal, Response
import json

# Read poll_id from test_poll.py
with open('test_poll_poll_id.txt', 'r') as f:
    poll_id = int(f.read().strip())

# Create session
session = SessionLocal()
try:
    # Query responses for our test poll
    responses = session.query(Response).filter_by(poll_id=poll_id, user_id=12345).all()
    
    # Print results
    print(f"\nResponses found: {len(responses)}")
    for resp in responses:
        print(f"Response: {resp.response}")
        
except Exception as e:
    print(f"Error querying responses: {e}")
finally:
    session.close()
