from src import database as db

if __name__ == '__main__':
    session = db.SessionLocal()
    poll = session.query(db.Poll).filter_by(poll_id=23).first()
    print(f'poll.options: {poll.options if poll else None}')
    print('responses:')
    for r in session.query(db.Response).filter_by(poll_id=23).all():
        print(f'user_id={r.user_id} | response={repr(r.response)}')
    session.close() 