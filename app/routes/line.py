# app/routes/line.py
from flask import Blueprint, request, session, redirect, render_template, url_for, flash, jsonify
import requests
from app.models import db, CustomerUser, ChargeHistory
from app.extensions import mail
from app.routes import delete_session
from flask_mail import Message
import os
import re
import json
from flask_login import login_user, login_required, logout_user
from app.decorators import role_required
from app.extensions import csrf
import redis
import msgpack
import pytz
from datetime import datetime, timedelta

line_bp = Blueprint('line_bp', __name__)
r = redis.StrictRedis(host=os.getenv('REDIS_HOST', 'localhost'), port=6379, db=0)

web_url = os.getenv('web_url')
channel_id = os.getenv('channel_id')
channel_secret = os.getenv('channel_secret')
mail_admin = os.getenv('mail_admin')
mail_admin_employee = os.getenv('mail_admin_employee')
mail_admin_white = os.getenv('mail_admin_white')
mail_admin_orange = os.getenv('mail_admin_orange')
mail_admin_white_temp = os.getenv('mail_admin_white_temp')
mail_admin_orange_temp = os.getenv('mail_admin_orange_temp')

department_list = [
    "ฝอก.", "ฝตส.", "ฝพธ.", "ฝปภ.", "ฝบฟ.", "ฝบก.", "ฝอจ.", "ฝวฟ.", "ฝวจ.", "ฝจห.",
    "ฝพด.", "ฝอบ.", "ฝกส.", "ฝบค.", "ฝคฟ.", "ฝบร.", "ฝทภ.", "ฝผก.", "ฝพอ.", "ฝศก.",
    "ฝบส.", "ฝสอ.", "ฝสส.", "ฝทม.", "ฝอร.", "ฝกม.", "ฝกพ.", "ฝบช.", "ฝกง.", "ฝงป.", 
    "ฝตพ.", "ฝธค.", "ฝธข.", "ฝจย.", "ฝวท.", "ฝพท.", "ฝคฐ.", "ฝมธ.", "สภส.", "ฟขล.", 
    "ฟขต.", "ฟขส.", "ฟขข.", "ฟขก.", "ฟขจ.", "ฟขว.", "ฟขท.", "ฟขน.", "ฟขญ.", "ฟขอ.", 
    "ฟขธ.", "ฟขป.", "ฟขพ.", "ฟขบ.", "ฟขร.", "ฟขม.", "ฟขง."
]

@line_bp.route('/dashboard')
@login_required
@role_required('SuperAdmin', 'Admin')
def dashboard():
    # if 'admin' not in session:
    #     return redirect(url_for('admin_bp.login'))
    users = CustomerUser.query.all()
    return render_template('admin/dashboard.html', users=users)

@csrf.exempt
@line_bp.route('/linelogin')
def linelogin():
    line_login_url = (
        'https://access.line.me/oauth2/v2.1/authorize'
        f'?response_type=code&client_id={channel_id}'
        f'&redirect_uri={web_url}/callback'
        '&state=random123&scope=openid%20profile&bot_prompt=normal'
    )
    print("Redirecting to LINE login URL:", line_login_url)
    return redirect(line_login_url)

@line_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('ออกจากระบบเรียบร้อยแล้ว', 'success')
    return redirect(url_for('line_bp.linelogin'))

@line_bp.route('/callback')
def callback():
    print("Callback route accessed")
    code = request.args.get('code')
    token_url = 'https://api.line.me/oauth2/v2.1/token'
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': f'{web_url}/callback',
        'client_id': channel_id,
        'client_secret': channel_secret
    }

    response = requests.post(token_url, headers=headers, data=data)
    token_data = response.json()
    access_token = token_data.get('access_token')

    profile_url = 'https://api.line.me/v2/profile'
    headers = {'Authorization': f'Bearer {access_token}'}
    profile_res = requests.get(profile_url, headers=headers)
    profile = profile_res.json()

    user_id = profile.get('userId')
    display_name = profile.get('displayName')
    picture_url = profile.get('pictureUrl')

    customer = CustomerUser.query.filter_by(user_id=user_id).first()
    session['user_id'] = user_id
    session['display_name'] = display_name
    session['picture_url'] = picture_url
    session['token_id'] = customer.token_id if customer else None
    print("department_list:", department_list)

    if customer:
        login_user(customer)
        # record = ChargeHistory.query.filter_by(user_id=user_id).first()
        # return render_template('customer_home.html', customer=customer, user_id=user_id, display_name=display_name, picture_url=picture_url)
        return redirect(url_for('line_bp.customer_home'))
    else:
        return render_template('register_form.html', user_id=user_id, display_name=display_name, picture_url=picture_url, department_list=department_list)


# --- server-side validation helpers ---
def valid_name(name):
    return bool(re.match(r'^[\u0E00-\u0E7Fa-zA-Z\s]{2,}$', name))

def valid_phone(phone):
    return bool(re.match(r'^0[0-9]{9}$', phone))

def valid_plate(plate):
    # 1-7 chars Thai/English/digits, no spaces/special
    return bool(re.match(r'^[0-9\u0E00-\u0E7Fa-zA-Z]{1,7}$', plate))

# Allow GET and POST (GET -> render form; POST -> handle submit)
@line_bp.route('/register', methods=['GET','POST'])
@csrf.exempt
def register():
    print("Register route accessed with method:", request.method)
    if request.method == 'GET':
        # render the same register.html template
        user_id = None  # or get from session/context
        return render_template('register.html', user_id=user_id)

    # === POST handling ===
    # Note: template currently uses names: employee_id and license_plate[]
    user_id = request.form.get('user_id')
    first_name = (request.form.get('first_name') or '').strip()
    last_name = (request.form.get('last_name') or '').strip()
    phone = (request.form.get('phone') or '').strip()
    department = (request.form.get('department') or '').strip()
    driver_type = (request.form.get('driver_type') or '').strip()
    employee_id = (request.form.get('employee_id') or '').strip()
    license_list = request.form.getlist('license_plate[]') or []

    print("Form data:", dict(request.form))
    print("Driver type:", driver_type)

    errors = []
    if not valid_name(first_name):
        errors.append('ชื่อไม่ถูกต้อง')
    if not valid_name(last_name):
        errors.append('นามสกุลไม่ถูกต้อง')
    if not valid_phone(phone):
        errors.append('เบอร์โทรศัพท์ไม่ถูกต้อง (รูปแบบ 081-234-5678)')
    if not department:
        errors.append('หน่วยงานห้ามว่าง')
    if not driver_type:
        errors.append('เลือกประเภทผู้ขับรถ')

    # ถ้าเลือกเป็น "พนักงาน กฟน." ต้องมีรหัสพนักงาน 7 หลัก (หน้าเป็นไทย)
    if driver_type == 'พนักงาน MEA':
        if not re.match(r'^[0-9]{7}$', employee_id):
            errors.append('รหัสพนักงานต้องเป็นตัวเลข 7 หลัก')

    clean_plate = []
    for p in license_list:
        p = (p or '').strip()
        if not p:
            continue
        if not valid_plate(p):
            errors.append(f'ป้ายทะเบียนไม่ถูกต้อง: {p}')
        else:
            clean_plate.append(p)

    if not clean_plate:
        errors.append('ต้องมีป้ายทะเบียนอย่างน้อย 1 รายการ')

    # ถ้ามี error ส่งกลับเป็น JSON (fetch รอบรับ JSON)
    if errors:
        return jsonify({"status": "error", "errors": errors}), 400

    # compute start_date and exp_date in Asia/Bangkok
    tz = pytz.timezone('Asia/Bangkok')
    now = datetime.now(tz)
    start_date = now.date().isoformat()

    # หาก driver_type เป็น "คนขับรถชั่วคราวสีส้มหรือคนขับรถชั่วคราวสีขาว" ให้ exp +7 วัน (ชื่อไทย)
    if driver_type == 'คนขับรถชั่วคราวสีส้ม' or driver_type == 'คนขับรถชั่วคราวสีขาว':
        exp_dt = (now + timedelta(days=14)).date().isoformat()
    else:
        exp_dt = 'none'

    # store (example using SQLAlchemy model CustomerUser)
    reg = CustomerUser(
        user_id=user_id,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        department=department,
        driver_type=driver_type,
        employee_id=employee_id if employee_id else None,
        license_plate=','.join(clean_plate),
        start_date=start_date,
        exp_date=exp_dt
    )
    db.session.add(reg)
    db.session.commit()

    # ส่งอีเมลแจ้งผู้ดูแลระบบ
    role_map = {
    "mail_admin_orange": ["คนขับรถสีส้ม", "คนขับรถชั่วคราวสีส้ม"],
    "mail_admin_white": ["คนขับรถสีขาว", "คนขับรถชั่วคราวสีขาว"],
    "mail_admin_employee": ["พนักงาน MEA"]
}

    # หา email admin ตาม driver_type
    mail_admin = None
    for admin_key, type_list in role_map.items():
        if driver_type in type_list:
            mail_admin = globals().get(admin_key)  # ดึงค่าตัวแปร mail_admin_orange / mail_admin_white ...
            break
    
    if not mail_admin:
        return f"ไม่พบ email admin ของประเภท {driver_type}"
    
    msg = Message(
        subject=f"ตรวจสอบการลงทะเบียน {driver_type} ระบบ Line2Charge",
        recipients=[mail_admin]
    )
    msg.body = (
        f"กรุณาตรวจสอบการลงทะเบียนของ: {driver_type}\n"
        f"ชื่อ: {first_name} {last_name}\n"
        f"หน่วยงาน: {department}\n"
        f"ติดต่อ: {phone}\n"
        f"ป้ายทะเบียน: {', '.join(clean_plate)}\n"
        f"ลิงก์ข้อมูลผู้ใช้: {web_url}/admin/customer"
    )
    print("Sending email to admin:", mail_admin)
    print("Email body:", msg.body)

    try:
        mail.send(msg)
    except Exception as e:
        print(f"[register] Email error: {e}")

    return jsonify({"status": "ok"})

def decode_dict(data):
    return {
        (k.decode() if isinstance(k, bytes) else k):
        (v.decode() if isinstance(v, bytes) else v)
        for k, v in data.items()
    }

def get_active_charging_session(user_id):
    session_keys = r.keys("session:*")
    active_session = None
    check_multi_session = False

    for key in session_keys:
        raw_data = r.get(key)
        if not raw_data:
            continue

        try:
            data = msgpack.unpackb(raw_data, raw=True)
            decoded = decode_dict(data)
        except Exception as e:
            print(f"Error decode {key}: {e}")
            continue

        # filter: ต้องเป็น user_id เดียวกัน
        if decoded.get("user_id") == user_id:
            # filter: ต้องมี charging_session อยู่
            if not check_multi_session:
                charging_data = decode_dict(decoded.get("charging_data", {}))
                transaction_id = charging_data.get("transaction_id")
                print(f"transaction_id", transaction_id)
                print(f"Decoded charging_data for session {key}: {charging_data}")  # Debug log
                if transaction_id:
                    active_session = {
                        "session_key": key.decode(),
                        "user_id": decoded.get("user_id"),
                        "charging_session": decoded.get("charging_session"),
                        "charging_data": decoded.get("charging_data")
                    }
                    check_multi_session = True
                    delete_session(key.decode())
                    print("Deleted active session after retrieval:", session_key)
                    print(f"Active session found: {active_session}")  # Debug log
                else:
                    session_key = key.decode()
                    r.delete(session_key)
                    print(f"Inactive session found for user {user_id}, deleted session {session_key}.")  # Debug log

            else:
                # ลบ session ที่เหลือ
                session_key = key.decode()
                r.delete(session_key)
                print(f"Multiple active sessions found for user {user_id}, deleted session {session_key}.")  # Debug log

    return active_session

def cleanup_user_sessions(user_id):
    session_keys = r.keys("session:*")
    active_sessions = []
    inactive_sessions = []

    for key in session_keys:
        raw_data = r.get(key)
        if not raw_data:
            continue

        try:
            data = msgpack.unpackb(raw_data, raw=True)
            decoded = decode_dict(data)
        except Exception as e:
            print(f"Error decode {key}: {e}")
            continue

        if decoded.get("user_id") == user_id:
            if decoded.get("charging_session"):
                active_sessions.append((key, decoded))
            else:
                inactive_sessions.append((key, decoded))

    # ✅ กำหนดว่าจะเก็บ active session ไว้ตัวเดียว
    keep_session = None
    if active_sessions:
        # เก็บ session ล่าสุด (Redis key ล่าสุด)
        keep_session = active_sessions[-1]
        # ลบ active session ตัวอื่น
        for key, _ in active_sessions[:-1]:
            r.delete(key)

    # ลบ inactive session ทั้งหมด
    for key, _ in inactive_sessions:
        r.delete(key)

    # return ข้อมูล session ที่เหลืออยู่
    if keep_session:
        key, data = keep_session
        if isinstance(data.get("charging_data"), dict):
            data["charging_data"] = decode_dict(data["charging_data"])
        return {"session_key": key.decode(), **data}

    return None

def is_expired(exp_date_str):
    if not exp_date_str or exp_date_str.lower() == 'none':
        print("No expiration date set.")
        return False  # ไม่มีวันหมดอายุ

    try:
        exp_date = datetime.strptime(exp_date_str, "%Y-%m-%d").date()
        tz = pytz.timezone('Asia/Bangkok')
        today = datetime.now(tz).date()
        print(f"Expiration date: {exp_date}, Today: {today}")
        return today > exp_date
    except ValueError:
        return False

@line_bp.route('/home', methods=['GET'])
def customer_home():
    user_id = session.get('user_id')
    print(f"Customer home accessed by user_id: {user_id}")  # Debug log
    if not user_id:
        print("No user_id in session, redirecting to login.")
        return redirect(url_for('line_bp.linelogin'))
    display_name = session.get('display_name')
    picture_url = session.get('picture_url')
    customer = CustomerUser.query.filter_by(user_id=user_id).first()
    active_session = get_active_charging_session(user_id)
    print(f"Active session for user {user_id}: {active_session}")  # Debug log
    if active_session:
        charging_session = True
        charging_data = decode_dict(active_session.get('charging_data', {}))
        print(f"Charging data from active session: {charging_data}")  # Debug log
        charging_data = {
            "cpid": charging_data.get('cpid'),
            "connid": charging_data.get('connid'),
            "card_id": charging_data.get('card_id'),
            "selected_plate": charging_data.get('selected_plate'),
            "transaction_id": charging_data.get('transaction_id')
        }
        session['charging_data'] = charging_data
        session_key = active_session['session_key']
        # delete_session(session_key)

    first_name = customer.first_name if customer else "Guest"
    exp_date = customer.exp_date if customer else "none"
    print(f"Customer expiration date: {exp_date}")  # Debug log
    if is_expired(exp_date):
        print("หมดอายุแล้ว")
        flash('บัญชีของคุณหมดอายุ กรุณาติดต่อผู้ดูแลระบบ', 'danger')
        # customer = CustomerUser.query.get_or_404(user_id)
        db.session.delete(customer)
        db.session.commit()
        return render_template('register_form.html', user_id=user_id, display_name=display_name, picture_url=picture_url)
    else:
        print("ยังไม่หมดอายุ")
    
    # license_str = customer.license_plate or ""
    license_str = getattr(customer, "license_plate", "") or ""
    license_list = [plate.strip() for plate in license_str.split(",") if plate.strip()]
    print(f"License plates for user {user_id}: {license_list}")  # Debug log
    charginghistory = ChargeHistory.query.filter_by(user_id=user_id).order_by(ChargeHistory.start_time.desc()).all()
    return render_template("customer_home.html",
                        customer=customer,
                        user_id=user_id,
                        display_name=display_name,
                        picture_url=picture_url,
                        charging_session=charging_session if 'charging_session' in locals() else None,
                        charging_data=charging_data if 'charging_data' in locals() else None,
                        charginghistory=charginghistory,
                        license_list=license_list,)

# QR_PATTERN = re.compile(r'^[A-Za-z0-9\-\_{},":]{3,400}$')  # ตัวอย่าง: ปรับให้ตรงกับรูปแบบจริงของคุณ
def check_qr(qr_text):

    qr_str = qr_text.strip()

    # ตรวจสอบว่าเป็น JSON หรือไม่
    try:
        qr_data = json.loads(qr_str)
        # เป็น JSON
        cpid = qr_data.get("ChargePointID")
        connid = int(qr_data.get("ConnectorID", 0))
    except json.JSONDecodeError:
        # ไม่ใช่ JSON → ตรวจรูปแบบ TH*MEA
        # ตัวอย่าง: TH*MEA*E*001rddNC2100040*1
        match = re.search(r'\*0*(\d+)(rddNC21\w*|rddNC20\w*|rddNC42\w*|fmd\w*)\*(\d+)', qr_str, re.IGNORECASE)
        if match:
            connid = int(match.group(1))  # เลขจากหลัง *E*
            cpid = match.group(2)     # ค่า CPID
            # หมายเหตุ: match.group(3) คือเลข ConnectorID ที่ท้ายสตริง อาจไม่ใช้

    # ตรวจ format
    pattern_uuid = re.search(r'"UUID"\s*:\s*"[^"]+"', qr_str)
    pattern_thmea = re.search(r'\bTH\*MEA\b', qr_str)
    check_qr_format = bool(pattern_uuid or pattern_thmea)

    # ตรวจ cp
    check_qr_cp = bool(re.search(r'(rddNC21\w*|rddNC20\w*|rddNC42\w*|fmd\w*)', qr_str, re.IGNORECASE))

    # Logic ตามเงื่อนไข
    if check_qr_format and check_qr_cp:
        return {"valid": True, "message": "สแกน QR Code สำเร็จ", "cpid": cpid, "connid": connid}
    elif check_qr_format and not check_qr_cp:
        return {"valid": False, "message": "ไม่อนุญาตให้ใช้เครื่องชาร์จนี้", "cpid": None, "connid": None}
    else:
        return {"valid": False, "message": "QR Code ไม่ถูกต้อง", "cpid": None, "connid": None}

# def idtoken_convert(self, id_token):
#     ascii_id_token = id_token.encode().hex()[:20]
#     print(f"Converted id_token: {ascii_id_token}")  # Debug log
#     # แปลง id_token เป็น user_id (ตัวอย่าง)
#     return ascii_id_token

def idtoken_convert(id_token):
    # แปลง string เป็น hex แล้วตัดเฉพาะ 20 ตัวแรก
    ascii_id_token = id_token.encode().hex()[:20]
    print(f"Converted id_token: {ascii_id_token}")
    return ascii_id_token

@line_bp.route('/scan', methods=['GET'])
def scan_page():
    user_id = session.get('user_id')
    customer = CustomerUser.query.filter_by(user_id=user_id).first()
    license_plate = customer.license_plate.split(',') if customer and customer.license_plate else []
    selected_plate = request.args.get('plate')
    token_id = idtoken_convert(selected_plate) if selected_plate else None
    session['token_id'] = token_id
    session['selected_plate'] = selected_plate
    print(f"Scan page accessed by user {user_id} with selected plate: {token_id}")  # Debug log
    # idtoken_convert(None, token_id)
    print(f"Converted token_id: {token_id}")  # Debug log
    # หน้า scan (เต็มจอ) - ถ้าต้องการให้ path เป็น /scan ให้ map ใน main app หรือ change url_prefix
    return render_template('scanqr.html',customer=customer, user_id=user_id, token_id=token_id, license_plate=license_plate, selected_plate=selected_plate)

@line_bp.route('/receive_qr', methods=['POST'])
def receive_qr():
    """
    รับ JSON: { "data": "<decoded QR text>" }
    เก็บไว้ใน session['qr'] และตรวจ format เบื้องต้น (valid/invalid)
    """
    payload = request.get_json(silent=True)
    print(f"Received payload: {payload}")  # Debug log
    if not payload or 'data' not in payload:
        return jsonify({"success": False, "message": "missing data"}), 400

    qr_text = payload['data'].strip()

    # ตรวจ format
    check = check_qr(qr_text)

    # เก็บลง session
    session['qr'] = check
    session['qr_valid'] = check['valid']

    # ถ้าไม่ valid ล้าง session
    if not check['valid']:
        session.pop('qr', None)
        session.pop('qr_valid', None)

    print(f"QR received: {qr_text}, valid: {check['valid']}, message: {check['message']}")  # Debug log  

    return jsonify({
        "valid": check['valid'],
        "message": check['message'],
        "cpid": check['cpid'],
        "connid": check['connid']
    }), 200

@line_bp.route('/clear_scan', methods=['GET'])
def clear_scan():
    session['charging_session'] = True
    session.pop('qr', None)
    session.pop('qr_valid', None)
    return '', 200

@line_bp.route('/charging_session', methods=['POST'])
def charging_session():
    user_id = session.get('user_id')
    display_name = session.get('display_name')
    picture_url = session.get('picture_url')

    customer = CustomerUser.query.filter_by(user_id=user_id).first()

    return render_template("charging_session.html",
                           customer=customer,
                           user_id=user_id,
                           display_name=display_name,
                           picture_url=picture_url)

@line_bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    user_id = session.get('user_id')
    customer = CustomerUser.query.filter_by(user_id=user_id).first()
    phone= customer.phone if customer else ''
    department= customer.department if customer else ''
    driver_type= customer.driver_type if customer else ''
    license= customer.license_plate.split(',') if customer and customer.license_plate else []

    if request.method == 'POST':
        driver_type = (request.form.get('driver_type') or '').strip()
        phone_new = (request.form.get('phone') or '').strip()
        department_new = (request.form.get('department') or '').strip()
        license_list_new = request.form.getlist('license_plate[]') or []
        print("Form data for edit_profile:", dict(request.form))

        errors = []
        if not valid_phone(phone_new):
            errors.append('เบอร์โทรศัพท์ไม่ถูกต้อง (รูปแบบ 081-234-5678)')

        clean_plate = []
        for p in license_list_new:
            p = (p or '').strip()
            if not p:
                continue
            if not valid_plate(p):
                errors.append(f'ป้ายทะเบียนไม่ถูกต้อง: {p}')
            else:
                clean_plate.append(p)

        if not clean_plate:
            errors.append('ต้องมีป้ายทะเบียนอย่างน้อย 1 รายการ')

        if errors:
            return jsonify({"status": "error", "errors": errors}), 400

        # อัพเดตข้อมูล
        status_updates = []
        status_phone = ''
        status_department = '' 
        status_license = ''

        # ตรวจสอบรายการที่มีการแก้ไข
        if phone_new != phone:
            status_phone = f"เปลี่ยนเบอร์โทรศัพท์จาก {phone} เป็น {phone_new}"
            phone = phone_new

        if department_new != department:
            status_department = f"เปลี่ยนหน่วยงานจาก {department} เป็น {department_new}"
            status_updates.append(status_department)
            department = department_new
            is_verified = False

        if license_list_new != license:
            status_license = f"เปลี่ยนป้ายทะเบียนจาก {license} เป็น {license_list_new}"
            status_updates.append(status_license)
            license = license_list_new
            is_verified = False

        # รวมเฉพาะรายการที่เปลี่ยนจริง
        if status_updates:
            changes_text = "\n".join(status_updates) if status_updates else "ไม่มีรายการที่ถูกแก้ไข"
        
            customer.phone = phone
            customer.department = department
            customer.license_plate = ','.join(clean_plate)
            customer.is_verified = is_verified if 'is_verified' in locals() else customer.is_verified
            
            print("status_phone:", status_phone)
            print("status_department:", status_department)
            print("status_license:", status_license)

            # ส่งอีเมลแจ้งผู้ดูแลระบบ
            role_map = {
                "mail_admin_orange": ["คนขับรถสีส้ม", "คนขับรถชั่วคราวสีส้ม"],
                "mail_admin_white": ["คนขับรถสีขาว", "คนขับรถชั่วคราวสีขาว"],
                "mail_admin_employee": ["พนักงาน MEA"]
            }

            # หา email admin ตาม driver_type
            mail_admin = None
            for admin_key, type_list in role_map.items():
                if driver_type in type_list:
                    mail_admin = globals().get(admin_key)  # ดึงค่าตัวแปร mail_admin_orange / mail_admin_white ...
                    break
            
            if not mail_admin:
                return f"ไม่พบ email admin ของประเภท {driver_type}"

            msg = Message(
                subject=f"ตรวจสอบการแก้ไขข้อมูล {driver_type} ระบบ Line2Charge",
                recipients=[mail_admin]
            )
            msg.body = (
                f"กรุณาตรวจสอบการแก้ไขข้อมูลผู้ใช้:\n"
                f"ชื่อ: {customer.first_name} {customer.last_name}\n"
                f"หน่วยงานปัจจุบัน: {department}\n"
                f"ติดต่อปัจจุบัน: {phone}\n"
                f"\nรายการที่แก้ไข:\n{changes_text}\n\n"
                f"ลิงก์ข้อมูลผู้ใช้: {web_url}/admin/customer"
            )
            try:
                mail.send(msg)
            except Exception as e:
                return f"ไม่ได้แจ้งผู้ดูแลระบบ: {e}"
            
        db.session.add(customer)
        db.session.commit()
        return jsonify({"status": "ok"})

    return render_template("edit_profile.html",
        user_id=user_id,
        phone=phone,
        department=department,
        license_list=license,
        customer=customer,
        driver_type=driver_type,
        department_list=department_list
        )

