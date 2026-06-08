# app/models/admin_user.py
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db
from flask_login import UserMixin

class AdminUser(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(100), nullable=False)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    role = db.Column(db.String(20), default='admin')
    phone = db.Column(db.String(20))
    mea_id = db.Column(db.String(50))
    departments = db.Column(db.String(100))


    # ตั้งค่ารหัสผ่าน (เก็บแบบ hash)
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # ตรวจสอบรหัสผ่าน
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    
