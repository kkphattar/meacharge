# app/models/admin_log.py
from app.models import db
from datetime import datetime, timezone


class AdminLog(db.Model):
    __tablename__ = 'admin_log'

    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, nullable=True)
    username = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(50), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    detail = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    user_agent = db.Column(db.String(300), nullable=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
