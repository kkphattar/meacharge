from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf import CSRFProtect
from flask_mail import Mail

csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)
mail = Mail()