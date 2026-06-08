from app.models import db
from datetime import datetime

class ChargeHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100))
    transaction_id = db.Column(db.Integer)
    charge_point_id = db.Column(db.String(100))
    connector_id = db.Column(db.Integer)
    start_time = db.Column(db.DateTime, default=datetime.utcnow)
    stop_time = db.Column(db.DateTime, default=datetime.utcnow)
    energy_used = db.Column(db.Float)
    selected_plate=db.Column(db.String(50))
