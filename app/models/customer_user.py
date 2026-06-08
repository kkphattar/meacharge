# app/models/customer_user.py
from app.models import db
from flask_login import UserMixin
from datetime import datetime, timedelta
class CustomerUser(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100), unique=True, nullable=False)
    first_name = db.Column(db.String(100))
    last_name = db.Column(db.String(100))
    phone = db.Column(db.String(100))
    token_id = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(100))
    license_plate = db.Column(db.String(50))
    is_verified = db.Column(db.Boolean, default=False)
    driver_type = db.Column(db.String(64))
    employee_id = db.Column(db.String(16), nullable=True)
    start_date = db.Column(db.String(32))  # ISO date string
    exp_date = db.Column(db.String(32))    # ISO date string or 'none'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'phone': self.phone,
            'token_id': self.token_id,
            'department': self.department,
            'license_plate': self.license_plate,
            'driver_type': self.driver_type,
            'employee_id': self.employee_id,
            'start_date': self.start_date,
            'exp_date': self.exp_date,
            'is_verified': self.is_verified
        }


