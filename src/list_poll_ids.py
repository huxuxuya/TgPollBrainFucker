from src import database as db

if __name__ == '__main__':
    session = db.SessionLocal()
    print('responses:')
    for r in session.query(db.Response).all():
        print(f'poll_id={r.poll_id} | user_id={r.user_id} | response={r.response}')
    print('\npoll_exclusions:')
    for e in session.query(db.PollExclusion).all():
        print(f'poll_id={e.poll_id} | user_id={e.user_id}')
    print('\npoll_settings:')
    for s in session.query(db.PollSetting).all():
        print(f'poll_id={s.poll_id}')
    print('\npoll_option_settings:')
    for o in session.query(db.PollOptionSetting).all():
        print(f'poll_id={o.poll_id} | option_index={o.option_index}')
    session.close() 