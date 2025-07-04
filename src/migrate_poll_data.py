from src import database as db

OLD_POLL_ID = 23
NEW_POLL_ID = 93139

def migrate_poll_data(old_poll_id, new_poll_id):
    session = db.SessionLocal()
    try:
        # Responses
        responses = session.query(db.Response).filter_by(poll_id=old_poll_id).all()
        for r in responses:
            # Проверка на дубли
            exists = session.query(db.Response).filter_by(poll_id=new_poll_id, user_id=r.user_id, response=r.response).first()
            if not exists:
                r.poll_id = new_poll_id
        # Poll exclusions
        exclusions = session.query(db.PollExclusion).filter_by(poll_id=old_poll_id).all()
        for e in exclusions:
            exists = session.query(db.PollExclusion).filter_by(poll_id=new_poll_id, user_id=e.user_id).first()
            if not exists:
                e.poll_id = new_poll_id
        # Poll settings
        old_setting = session.query(db.PollSetting).filter_by(poll_id=old_poll_id).first()
        if old_setting:
            exists = session.query(db.PollSetting).filter_by(poll_id=new_poll_id).first()
            if not exists:
                old_setting.poll_id = new_poll_id
        # Poll option settings
        option_settings = session.query(db.PollOptionSetting).filter_by(poll_id=old_poll_id).all()
        for s in option_settings:
            exists = session.query(db.PollOptionSetting).filter_by(poll_id=new_poll_id, option_index=s.option_index).first()
            if not exists:
                s.poll_id = new_poll_id
        session.commit()
        print(f"Миграция данных с poll_id={old_poll_id} на poll_id={new_poll_id} завершена.")
    except Exception as e:
        session.rollback()
        print(f"Ошибка миграции: {e}")
    finally:
        session.close()

if __name__ == '__main__':
    migrate_poll_data(OLD_POLL_ID, NEW_POLL_ID) 