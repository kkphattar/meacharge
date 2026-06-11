# app/models/notify_email.py
from app.models import db
from datetime import datetime

DRIVER_TYPES = [
    "พนักงาน MEA",
    "คนขับรถสีส้ม",
    "คนขับรถสีขาว",
    "คนขับรถชั่วคราวสีส้ม",
    "คนขับรถชั่วคราวสีขาว",
]

class NotifyEmail(db.Model):
    __tablename__ = 'notify_email'
    id = db.Column(db.Integer, primary_key=True)
    driver_type = db.Column(db.String(64), nullable=False, index=True)
    email = db.Column(db.String(200), nullable=False)
    label = db.Column(db.String(100), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('driver_type', 'email', name='uq_driver_email'),
    )
