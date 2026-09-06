from app.database import SessionLocal
from app.models.email import Email, EmailReply
from app.services.gmail_send import send_reply_via_gmail

s=SessionLocal()
e = s.query(Email).first()
if not e:
    print('no email rows found')
else:
    print('email', e.id, e.sender_email)
    r = EmailReply(email_id=e.id, subject=f'Re: {e.subject}', body='Test reply from automated test', is_draft=False)
    s.add(r)
    s.commit()
    s.refresh(r)
    print('reply', r.id)
    ok = send_reply_via_gmail(e, r)
    print('ok', ok)
    s.close()
