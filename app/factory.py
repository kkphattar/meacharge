# app/factory.py
from flask import Flask
# from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from flask_session import Session
import redis

from app.models import db, AdminUser
from app.routes.line import line_bp
from app.routes.admin import admin_bp
from app.routes.api import api_bp

from dotenv import load_dotenv
from flask_login import LoginManager
import os

# from flask_wtf import CSRFProtect
from datetime import timedelta
from .extensions import limiter, csrf

load_dotenv()  # โหลด .env
login_manager = LoginManager()

mail = Mail()

def create_app():
    app = Flask(__name__)
    limiter.init_app(app)
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('database_url')
    app.config['SECRET_KEY'] = os.getenv('secret_key')
    app.config['MAIL_SERVER'] = os.getenv('mail_server')
    app.config['MAIL_PORT'] = 587
    app.config['MAIL_USE_TLS'] = True
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('mail_username')
    app.config['MAIL_USERNAME'] = os.getenv('mail_username')
    app.config['MAIL_PASSWORD'] = os.getenv('mail_password')

    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=240)  # เปลี่ยนตามต้องการ เช่น 15, 30 นาที
    app.config["SESSION_TYPE"] = "redis"
    app.config["SESSION_PERMANENT"] = False
    app.config["SESSION_USE_SIGNER"] = True
    app.config["SESSION_REDIS"] = redis.StrictRedis(host="localhost", port=6379, db=0)
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SECURE'] = True        # ใช้ HTTPS เท่านั้น
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'



# Init LoginManager
    login_manager.init_app(app)
    login_manager.login_view = 'admin_bp.login'  # หรือชื่อ endpoint ของ login ของคุณ

    # csrf = CSRFProtect(app)

    db.init_app(app)
    mail.init_app(app)
    Session(app)

    with app.app_context():  # 👈 เพิ่ม block นี้
        db.create_all()

    app.register_blueprint(line_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(api_bp)

    return app

@login_manager.user_loader
def load_user(user_id):
    return AdminUser.query.get(int(user_id))
