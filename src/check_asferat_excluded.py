from src import database as db

CHAT_ID = -1002504857152
USERNAME = 'asferat'

session = db.SessionLocal()
participants = session.query(db.Participant).filter_by(chat_id=CHAT_ID).all()
asferat_list = [p for p in participants if p.username == USERNAME]

if not asferat_list:
    print('Пользователь asferat не найден в participants для этого чата.')
else:
    print('Данные asferat:')
    for p in asferat_list:
        print(f'user_id={p.user_id} | username={p.username} | first_name={p.first_name} | last_name={p.last_name} | excluded={p.excluded}')
    user_id = asferat_list[0].user_id
    poll_exclusions = session.query(db.PollExclusion).filter_by(user_id=user_id).all()
    print('\nИсключения (poll_exclusions) для этого user_id:')
    if not poll_exclusions:
        print('Нет записей в poll_exclusions для этого пользователя.')
    else:
        for e in poll_exclusions:
            print(f'poll_id={e.poll_id} | user_id={e.user_id}')
session.close() 