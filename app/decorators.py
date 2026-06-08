# app/decorators.py

from functools import wraps
from flask import abort
from flask_login import current_user

def role_required(*roles):
    def decorator(view_function):
        @wraps(view_function)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)  # ไม่ได้ login
            if current_user.role not in roles:
                abort(403)  # ไม่มีสิทธิ์
            return view_function(*args, **kwargs)
        return wrapper
    return decorator
