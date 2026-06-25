# app/routes/admin.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response
from app.models import AdminUser, CustomerUser, ChargeHistory, AdminLog, NotifyEmail, db
import csv
import io
import os
from datetime import datetime
import random, string
import re  # ใช้สำหรับตรวจสอบ email
from app.utils.mail import send_mail
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from .forms import LoginForm
from app.decorators import role_required
from sqlalchemy.exc import IntegrityError
from app.extensions import csrf, limiter
import redis
import msgpack

admin_bp = Blueprint('admin_bp', __name__, url_prefix='/admin')
r = redis.StrictRedis(host=os.getenv('REDIS_HOST', 'localhost'), port=6379, db=0)


def log_action(action, detail='', username=None, admin_id=None, role=None):
    try:
        if username is None:
            username = current_user.username if current_user.is_authenticated else 'anonymous'
        if admin_id is None and current_user.is_authenticated:
            admin_id = current_user.id
        if role is None and current_user.is_authenticated:
            role = current_user.role
        entry = AdminLog(
            admin_id=admin_id,
            username=username,
            role=role,
            action=action,
            detail=detail[:2000] if detail else None,
            ip_address=request.remote_addr,
            user_agent=(request.user_agent.string or '')[:300],
        )
        db.session.add(entry)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        print(f"[AdminLog] {exc}")

@admin_bp.route('/', methods=['GET', 'POST'])
def home():
    return redirect(url_for('admin_bp.dashboard'))

@admin_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("3 per 1 minutes")  # จำกัด 5 ครั้งต่อ 10 นาที ต่อ IP
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = AdminUser.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            log_action('LOGIN_SUCCESS', username=user.username, admin_id=user.id, role=user.role)
            return redirect(url_for('admin_bp.dashboard'))
        log_action('LOGIN_FAILED', detail=f'username={form.username.data}',
                   username=form.username.data or 'unknown', admin_id=None, role=None)
    return render_template('admin/login.html', form=form)

@admin_bp.route('/forgot', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        user = AdminUser.query.filter_by(username=username, email=email).first()
        if user:
            new_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
            user.set_password(new_pass)
            db.session.commit()
            try:
                send_mail("รีเซ็ตรหัสผ่านของคุณ", [email], f"รหัสผ่านใหม่ของคุณคือ: {new_pass}")
            except Exception as e:
                return f"ไม่สามารถส่งอีเมลได้: {e}"
            return 'ส่งรหัสผ่านใหม่ไปยังอีเมลแล้ว'
        return 'ไม่พบข้อมูลผู้ใช้หรืออีเมลไม่ตรงกัน'
    return render_template('admin/forgot.html')

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    role = current_user.role

    # คนขับรถที่อยู่ในขอบเขตของ role ปัจจุบัน
    if role == 'SuperAdmin':
        customers = CustomerUser.query.all()
    elif role in role_map:
        customers = CustomerUser.query.filter(CustomerUser.driver_type.in_(role_map[role])).all()
    else:
        customers = []

    total_drivers = len(customers)
    verified_drivers = sum(1 for c in customers if c.is_verified)
    unverified_drivers = total_drivers - verified_drivers

    driver_type_counts = {}
    for c in customers:
        key = c.driver_type or 'ไม่ระบุ'
        driver_type_counts[key] = driver_type_counts.get(key, 0) + 1
    driver_type_counts = dict(sorted(driver_type_counts.items(), key=lambda x: x[1], reverse=True))

    # ข้อมูลการชาร์จในขอบเขตเดียวกัน
    if role == 'SuperAdmin':
        charge_rows = ChargeHistory.query.all()
        user_map = {c.user_id: c for c in CustomerUser.query.all()}
    else:
        user_ids = [c.user_id for c in customers]
        user_map = {c.user_id: c for c in customers}
        charge_rows = ChargeHistory.query.filter(ChargeHistory.user_id.in_(user_ids)).all() if user_ids else []

    # พลังงานรายเดือน (6 เดือนล่าสุด)
    now = datetime.utcnow()
    months = []
    y, m = now.year, now.month
    for _ in range(6):
        months.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    months.reverse()
    monthly_energy = {f'{y:04d}-{m:02d}': 0.0 for y, m in months}

    user_energy = {}
    total_energy = 0.0
    for r in charge_rows:
        energy = r.energy_used or 0
        total_energy += energy
        if r.start_time:
            key = r.start_time.strftime('%Y-%m')
            if key in monthly_energy:
                monthly_energy[key] += energy
        user_energy[r.user_id] = user_energy.get(r.user_id, 0) + energy

    top_users = sorted(user_energy.items(), key=lambda x: x[1], reverse=True)[:5]
    top_users_data = []
    for uid, energy in top_users:
        cust = user_map.get(uid)
        top_users_data.append({
            'name': cust.full_name() if cust else uid,
            'department': cust.department if cust else '-',
            'energy': round(energy, 2),
        })

    return render_template(
        'admin/dashboard.html',
        total_drivers=total_drivers,
        verified_drivers=verified_drivers,
        unverified_drivers=unverified_drivers,
        driver_type_counts=driver_type_counts,
        monthly_labels=list(monthly_energy.keys()),
        monthly_values=[round(v, 2) for v in monthly_energy.values()],
        total_energy=round(total_energy, 2),
        total_sessions=len(charge_rows),
        top_users=top_users_data,
    )


@admin_bp.route('/admin_users')
@login_required
@role_required('SuperAdmin', 'Admin_orange', 'Admin_white', 'Admin', 'admin')
def admin_users():
    users = AdminUser.query.all()
    return render_template('admin/admin_users.html', users=users)

@admin_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_user():

    if request.method == 'POST':
        username = request.form['username']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        email = request.form['email']
        role = request.form['role']
        password = request.form['password']
        confirm = request.form['confirm_password']
        phone = request.form['phone']
        mea_id = request.form['mea_id']
        departments = request.form['departments']

        if password != confirm:
            flash("รหัสผ่านไม่ตรงกัน", "danger")
            return render_template('admin/add_user.html')

        existing = AdminUser.query.filter_by(username=username).first()
        if existing:
            flash("Username นี้มีอยู่แล้ว", "danger")
            return render_template('admin/add_user.html')

        user = AdminUser(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            role=role,
            phone=phone,
            mea_id=mea_id,
            departments=departments
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()
        log_action('ADD_ADMIN', detail=f'username={username} role={role}')
        flash("เพิ่มผู้ใช้งานเรียบร้อย", "success")
        return redirect(url_for('admin_bp.admin_users'))

    return render_template('admin/add_user.html')

# ✅ แก้ไข admin
@admin_bp.route('/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
def edit_user(user_id):
    user = AdminUser.query.get_or_404(user_id)
    if current_user.role != 'SuperAdmin':
        flash('คุณไม่มีสิทธิ์ในการดำเนินการนี้', 'danger')
        return redirect(url_for('admin_bp.dashboard'))

    if request.method == 'POST':
        email = request.form['email']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        mea_id = request.form['mea_id']
        phone = request.form['phone']
        departments = request.form['departments']
        role = request.form['role']

        # ตรวจสอบอีเมลรูปแบบ
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            flash('อีเมลไม่ถูกต้อง', 'danger')
            return render_template('admin/edit_user.html', user=user)

        # ตรวจสอบ duplicate email (ที่ไม่ใช่ของ user นี้)
        existing_email = AdminUser.query.filter(AdminUser.email == email, AdminUser.id != user.id).first()
        if existing_email:
            flash('อีเมลนี้มีในระบบแล้ว', 'danger')
            return render_template('admin/edit_user.html', user=user)

        # อัปเดตข้อมูล
        user.email = email
        user.first_name = first_name
        user.last_name = last_name
        user.mea_id = mea_id
        user.phone = phone
        user.departments = departments
        user.role = role

        try:
            db.session.commit()
            log_action('EDIT_ADMIN', detail=f'target_id={user_id} role={role}')
            flash('✅ แก้ไขข้อมูลผู้ดูแลระบบเรียบร้อยแล้ว', 'success')
            return redirect(url_for('admin_bp.admin_users'))
        except Exception as e:
            db.session.rollback()
            flash(f'เกิดข้อผิดพลาดในการบันทึกข้อมูล: {str(e)}', 'danger')

    return render_template('admin/edit_user.html', user=user)

# ✅ ลบ admin
@admin_bp.route('/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    # if 'admin' not in session:
    #     return redirect(url_for('admin_bp.login'))

    user = AdminUser.query.get_or_404(user_id)
    log_action('DELETE_ADMIN', detail=f'target={user.username} id={user_id}')
    db.session.delete(user)
    db.session.commit()
    flash("ลบผู้ใช้เรียบร้อย", "success")
    return redirect(url_for('admin_bp.admin_users'))

@admin_bp.route('/logout')
@login_required
def logout():
    log_action('LOGOUT')
    logout_user()
    flash('ออกจากระบบเรียบร้อยแล้ว', 'success')
    return redirect(url_for('admin_bp.login'))

@admin_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user = AdminUser.query.get(current_user.id)

    if request.method == 'POST':
        # แก้ไขข้อมูลทั่วไป
        user.first_name = request.form['first_name']
        user.last_name = request.form['last_name']
        user.email = request.form['email']
        user.phone = request.form['phone']
        user.departments = request.form['departments']

        # เปลี่ยนรหัสผ่าน (optional)
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if current_password and new_password:
            if not check_password_hash(user.password_hash, current_password):
                flash('❌ รหัสผ่านปัจจุบันไม่ถูกต้อง', 'danger')
                return redirect(url_for('admin_bp.profile'))
            if new_password != confirm_password:
                flash('❌ ยืนยันรหัสผ่านไม่ตรงกัน', 'danger')
                return redirect(url_for('admin_bp.profile'))
            user.password_hash = generate_password_hash(new_password)
            log_action('CHANGE_PASSWORD')

        db.session.commit()
        log_action('UPDATE_PROFILE')
        flash('✅ อัปเดตข้อมูลเรียบร้อยแล้ว', 'success')
        return redirect(url_for('admin_bp.profile'))

    return render_template('admin/profile.html', user=user)

def decode_dict(data):
    return {
        (k.decode() if isinstance(k, bytes) else k):
        (v.decode() if isinstance(v, bytes) else v)
        for k, v in data.items()
    }
@admin_bp.route("/sessions")
@login_required
def list_sessions():
    session_keys = r.keys("session:*")
    sessions = []

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

        ttl = r.ttl(key)
        charging_data = decode_dict(decoded.get("charging_data", {}))
        print(f"charging_data: {charging_data}")
        print(f"decoded data: {decoded}")

        sessions.append({
            "user_id": decoded.get("user_id", "N/A"),
            "username": decoded.get("display_name", "N/A"),
            "transaction_id": charging_data.get("transaction_id", "N/A"),
            "key": key.decode(),
            "data": data,
            "ttl": ttl
        })
        print(f"sessions so far: {sessions}")
        print(f"Raw data: {raw_data}")
    return render_template("admin/session.html", sessions=sessions)

# Admin Route: ลบ Session
@admin_bp.route("/sessions/delete/<session_id>")
@login_required
def delete_session(session_id):
    log_action('DELETE_SESSION', detail=f'session_key={session_id}')
    r.delete(session_id)
    return redirect(url_for("admin_bp.list_sessions"))

role_map = {
    "Admin_orange": ["คนขับรถสีส้ม", "คนขับรถชั่วคราวสีส้ม"],
    "Admin_white": ["คนขับรถสีขาว", "คนขับรถชั่วคราวสีขาว"],
    "Admin": ["คนขับรถสีส้ม", "คนขับรถชั่วคราวสีส้ม", "คนขับรถสีขาว", "คนขับรถชั่วคราวสีขาว"],
    "admin": ["คนขับรถสีส้ม", "คนขับรถชั่วคราวสีส้ม", "คนขับรถสีขาว", "คนขับรถชั่วคราวสีขาว"],
}


@admin_bp.route('/customer')
@csrf.exempt
@login_required
def view_customer():
    # customer = CustomerUser.query.all()
    if current_user.role == "SuperAdmin":
        filtered_customers = CustomerUser.query.all()
    elif current_user.role in role_map:
        filtered_customers = CustomerUser.query.filter(CustomerUser.driver_type.in_(role_map[current_user.role])).all()
    else:
        filtered_customers = []
   
    customer_dict = [c.to_dict() for c in filtered_customers]
    print("Filtered customers:", customer_dict)
    return render_template('admin/customer.html', customer=customer_dict)

@admin_bp.route("/customers/<int:customer_id>/verify", methods=["POST"])
@login_required
def verify_customer_ajax(customer_id):
    if current_user.role not in ['SuperAdmin', 'Admin_orange', 'Admin_white', 'Admin', 'admin']:
        flash('คุณไม่มีสิทธิ์ในการยืนยันข้อมูลลูกค้า', 'danger')
        return redirect(url_for('admin_bp.view_customer'))

    print("Request data:", request.get_json())
    data=request.get_json()
    user_id=data.get("user_id")
    token_id=data.get("token_id")
    license_plate=data.get("license_plate")
    is_verified=data.get("is_verified")
    customer = CustomerUser.query.get_or_404(customer_id)
    print(user_id, token_id, license_plate, is_verified)
    print("Customer fetched:", customer)

    try:
        if is_verified:
            print("Verifying customer:", customer_id)
            # ตรวจสอบว่ามีทะเบียนรถซ้ำ
            duplicate = CustomerUser.query.filter(
                CustomerUser.license_plate == license_plate,
                CustomerUser.is_verified == True
            ).first()

            if duplicate:
                print("Found duplicate license plate:", duplicate.license_plate)
                # duplicate.is_verified = False
                # db.session.commit()

            # ตั้งค่าของ customer ปัจจุบัน
                try:
                    print("Setting customer as verified with token:", customer)
                    customer.is_verified = True
                    print("Token ID to set:", token_id)
                    customer.token_id = duplicate.token_id
                    duplicate.token_id = None  # ลบ token_id ของคนเก่า
                    db.session.commit()
                except IntegrityError:
                    db.session.rollback()
            else:
                customer.is_verified = True
                db.session.commit()       
        else:
            customer.is_verified = False
            db.session.commit()
        action = 'VERIFY_CUSTOMER' if is_verified else 'UNVERIFY_CUSTOMER'
        log_action(action, detail=f'customer_id={customer_id} license={license_plate}')
        return jsonify({"success": True, "is_verified": is_verified})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route('/customer/verify/<int:customer_id>', methods=['POST'])
@login_required
def verify_customer(customer_id):
    if current_user.role not in ['SuperAdmin', 'Admin']:
        flash('คุณไม่มีสิทธิ์ในการยืนยันข้อมูลลูกค้า', 'danger')
        return redirect(url_for('admin_bp.view_customer'))

    customer = CustomerUser.query.get_or_404(customer_id)

    # ตรวจสอบว่าทะเบียนรถนี้ถูก verified แล้วหรือยัง
    duplicate = CustomerUser.query.filter_by(license_plate=customer.license_plate, is_verified=True).first()

    if duplicate and duplicate.id != customer.id:
        # ถ้ามีทะเบียนซ้ำที่ถูก verified แล้ว และไม่ใช่ customer เดิม
        flash(f'ทะเบียน {customer.license_plate} มีการยืนยันแล้วกับลูกค้ารายอื่น หากดำเนินการต่อ จะยกเลิกการยืนยันรายการเดิม', 'warning')

        # ยกเลิกการ verify รายเก่า
        duplicate.is_verified = False
        db.session.commit()

    try:
        customer.is_verified = True
        db.session.commit()
        log_action('VERIFY_CUSTOMER', detail=f'customer_id={customer_id} name={customer.first_name} {customer.last_name}')
        flash(f'ยืนยันข้อมูลลูกค้า {customer.first_name} {customer.last_name} เรียบร้อยแล้ว', 'success')
    except IntegrityError:
        db.session.rollback()
        flash('เกิดข้อผิดพลาดในการบันทึกข้อมูล', 'danger')

    return redirect(url_for('admin_bp.view_customer'))

@admin_bp.route("/customers/<int:customer_id>/unverify", methods=["POST"])
@login_required
def unverify_customer(customer_id):
    customer=CustomerUser.query.get_or_404(customer_id)
    customer.is_verified=False
    db.session.commit()
    log_action('UNVERIFY_CUSTOMER', detail=f'customer_id={customer_id} name={customer.first_name} {customer.last_name}')
    return jsonify({"status":"success"})

@admin_bp.route("/customers/<int:customer_id>/pre_verify_check")
@login_required
def pre_verify_check(customer_id):
    customer = CustomerUser.query.get_or_404(customer_id)

    # ตรวจสอบทะเบียนซ้ำ
    existing = CustomerUser.query.filter(
        CustomerUser.license_plate==customer.license_plate,
        CustomerUser.is_verified==True,
        CustomerUser.id!=customer.id
    ).first()
    if existing:
        return jsonify({
            "status":"license_duplicate",
            "existing":{
                "id":existing.id, "first_name":existing.first_name,
                "last_name":existing.last_name, "department":existing.department
            }
        })

    # ตรวจสอบว่ามี token_id หรือยัง
    if not customer.token_id:
        return jsonify({"status":"need_token"})

    # ผ่านเงื่อนไข → is_verified ได้เลย
    customer.is_verified=True
    db.session.commit()
    log_action('VERIFY_CUSTOMER', detail=f'customer_id={customer_id} auto_verify')
    return jsonify({"status":"ok"})


@admin_bp.route("/customers/<int:customer_id>/replace_license", methods=["POST"])
@login_required
def replace_license(customer_id):
    new_customer=CustomerUser.query.get_or_404(customer_id)

    # หาคนเก่าที่ทะเบียนซ้ำ
    old_customer=CustomerUser.query.filter(
        CustomerUser.license_plate==new_customer.license_plate,
        CustomerUser.is_verified==True,
        CustomerUser.id!=new_customer.id
    ).first()

    if old_customer:
        # ย้าย token ไปให้คนใหม่
        new_customer.token_id = old_customer.token_id
        old_customer.is_verified=False
        old_customer.token_id=None
        new_customer.is_verified=True
        db.session.commit()
        log_action('REPLACE_LICENSE', detail=f'new_id={customer_id} old_id={old_customer.id} plate={new_customer.license_plate}')
        return jsonify({"status":"success"})

    return jsonify({"status":"error"})


@admin_bp.route('/update_token/<int:customer_id>', methods=['POST'])
@login_required
def update_token(customer_id):
    if current_user.role not in ['SuperAdmin', 'Admin']:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    token_id = request.json.get('token_id')
    if not token_id:
        return jsonify({'success': False, 'message': 'Token ID is required'}), 400

    customer = CustomerUser.query.get(customer_id)
    if not customer:
        return jsonify({'success': False, 'message': 'Customer not found'}), 404

    customer.token_id = token_id
    db.session.commit()
    log_action('UPDATE_TOKEN', detail=f'customer_id={customer_id} token={token_id}')
    return jsonify({'success': True, 'message': 'Token updated successfully'})

@admin_bp.route("/customers/<int:customer_id>/replace_token", methods=["POST"])
@login_required
def replace_token(customer_id):
    data = request.get_json()
    old_id = data.get("old_id")
    token_id = data.get("token_id")

    # ลบ token_id ของ user เก่า
    old_customer = CustomerUser.query.get(old_id)
    if old_customer:
        old_customer.token_id = None

    # บันทึก token_id ให้ user ใหม่
    new_customer = CustomerUser.query.get(customer_id)
    new_customer.token_id = token_id
    db.session.commit()
    log_action('REPLACE_TOKEN', detail=f'new_id={customer_id} old_id={old_id} token={token_id}')
    return jsonify({"status": "success"})

@admin_bp.route('/toggle_verify/<int:customer_id>', methods=['POST'])
@login_required
def toggle_verify(customer_id):
    if current_user.role not in ['SuperAdmin', 'Admin']:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    customer = CustomerUser.query.get(customer_id)
    if not customer:
        return jsonify({'success': False, 'message': 'Customer not found'}), 404

    # เช็คสถานะใหม่ที่ client ส่งมา
    new_status = request.json.get('is_verified', False)

    # ✅ Case: กำลังจะเปลี่ยนเป็น True
    if new_status:
        # 1. ต้องมี token_id
        if not customer.token_id:
            return jsonify({
                'success': False,
                'require_token': True,
                'message': 'ต้องใส่ Token ID ก่อนที่จะยืนยัน'
            }), 400

        # 2. ตรวจสอบทะเบียนซ้ำที่มี is_verified อยู่แล้ว
        existing = CustomerUser.query.filter(
            CustomerUser.license_plate == customer.license_plate,
            CustomerUser.is_verified == True,
            CustomerUser.id != customer.id
        ).first()

        if existing:
            # 👉 popup ฝั่ง frontend ควรถามว่าจะแทนที่หรือไม่
            return jsonify({
                'success': False,
                'duplicate_verified': True,
                'existing_customer': {
                    'id': existing.id,
                    'name': f"{existing.first_name} {existing.last_name}",
                    'department': existing.department,
                    'token_id': existing.token_id
                },
                'message': 'พบทะเบียนนี้ถูกยืนยันแล้ว ต้องการแทนที่หรือไม่'
            }), 409

        # ✅ ไม่มีซ้ำ → อนุญาต
        customer.is_verified = True
        db.session.commit()
        return jsonify({'success': True, 'message': 'Verified successfully'})

    # ✅ Case: ปิดสถานะ
    else:
        customer.is_verified = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'Unverified successfully'})
    
@admin_bp.route('/replace_verified/<int:old_id>/<int:new_id>', methods=['POST'])
@login_required
def replace_verified(old_id, new_id):
    if current_user.role not in ['SuperAdmin', 'Admin']:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    old_customer = CustomerUser.query.get(old_id)
    new_customer = CustomerUser.query.get(new_id)

    if not old_customer or not new_customer:
        return jsonify({'success': False, 'message': 'Customer not found'}), 404

    # 👉 โอน token_id ถ้ามี
    if old_customer.token_id:
        new_customer.token_id = old_customer.token_id

    # ปิดสถานะของเก่า
    old_customer.is_verified = False

    # เปิดสถานะของใหม่
    if not new_customer.token_id:
        return jsonify({
            'success': False,
            'require_token': True,
            'message': 'ต้องใส่ Token ID ให้ record ใหม่ก่อนยืนยัน'
        }), 400

    new_customer.is_verified = True
    db.session.commit()
    log_action('REPLACE_VERIFIED', detail=f'old_id={old_id} new_id={new_id}')
    return jsonify({'success': True, 'message': 'Replaced verified record successfully'})

@admin_bp.route("/customers/<int:customer_id>/delete", methods=["POST"])
@login_required
def customers_delete(customer_id):
    customer = CustomerUser.query.get_or_404(customer_id)
    log_action('DELETE_CUSTOMER', detail=f'customer_id={customer_id} name={customer.first_name} {customer.last_name} license={customer.license_plate}')
    db.session.delete(customer)
    db.session.commit()
    return jsonify({"status":"success"})

# @admin_bp.route('/customers/<int:customer_id>/save', methods=['POST'])
@admin_bp.route('/customers/save', methods=['POST'])
@login_required
def save_customer():
    print("Request data:", request.get_json())
    if current_user.role not in ['SuperAdmin', 'Admin_orange', 'Admin_white', 'Admin', 'admin']:
        return jsonify({'success': False, 'message': 'Permission denied'}), 403

    data = request.get_json()
    print("Data received for saving customer:", data)
    customer_id = data.get('customer_id')
    print("Customer ID:", customer_id)

    if customer_id:
        # แก้ไขข้อมูลลูกค้า
        customer = CustomerUser.query.get(customer_id)
        if not customer:
            return jsonify({'success': False, 'message': 'Customer not found'}), 404
    else:
        # สร้างลูกค้าใหม่
        customer = CustomerUser()

    customer.first_name = data.get('first_name')
    customer.last_name = data.get('last_name')
    customer.department = data.get('department')
    customer.license_plate = data.get('license_plate')
    customer.is_verified = data.get('is_verified', False)
    print("Updated customer data:", customer.to_dict())

    db.session.add(customer)
    db.session.commit()

    return jsonify({"status":"success"})


PER_PAGE = 50

@admin_bp.route('/charge_history')
@login_required
@role_required('SuperAdmin', 'Admin_orange', 'Admin_white', 'Admin', 'admin')
def charge_history():
    q = request.args.get('q', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    station = request.args.get('station', '').strip()
    page = max(1, request.args.get('page', 1, type=int))

    query = ChargeHistory.query

    if date_from:
        try:
            query = query.filter(ChargeHistory.start_time >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(ChargeHistory.start_time <= dt_to)
        except ValueError:
            pass
    if station:
        query = query.filter(ChargeHistory.charge_point_id == station)

    # ค้นหาข้อาม q จาก selected_plate หรือ charge_point_id
    if q:
        like = f'%{q}%'
        # join CustomerUser เพื่อค้นหาชื่อด้วย
        matching_user_ids = [
            c.user_id for c in CustomerUser.query.filter(
                db.or_(
                    CustomerUser.first_name.ilike(like),
                    CustomerUser.last_name.ilike(like),
                )
            ).all()
        ]
        query = query.filter(
            db.or_(
                ChargeHistory.selected_plate.ilike(like),
                ChargeHistory.charge_point_id.ilike(like),
                ChargeHistory.user_id.in_(matching_user_ids)
            )
        )

    query = query.order_by(ChargeHistory.start_time.desc())

    total_sessions = query.count()
    total_pages = max(1, (total_sessions + PER_PAGE - 1) // PER_PAGE)
    page = min(page, total_pages)

    raw_rows = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE).all()

    # join customer info และคำนวณ duration
    user_map = {c.user_id: c for c in CustomerUser.query.all()}

    class HistoryRow:
        pass

    history = []
    page_energy = 0.0
    for r in raw_rows:
        row = HistoryRow()
        row.__dict__.update(r.__dict__)
        row.customer = user_map.get(r.user_id)
        if r.start_time and r.stop_time:
            diff = r.stop_time - r.start_time
            row.duration_minutes = diff.total_seconds() / 60
        else:
            row.duration_minutes = None
        page_energy += r.energy_used or 0
        history.append(row)

    # summary stats (ทั้งหมด ไม่ใช่แค่หน้านี้)
    all_rows = query.all()
    total_energy = sum(r.energy_used or 0 for r in all_rows)
    unique_users = len({r.user_id for r in all_rows if r.user_id})
    unique_stations = len({r.charge_point_id for r in all_rows if r.charge_point_id})
    station_list = sorted({r.charge_point_id for r in ChargeHistory.query.with_entities(ChargeHistory.charge_point_id).distinct() if r.charge_point_id})

    filters = {'q': q, 'date_from': date_from, 'date_to': date_to, 'station': station}

    def build_query(**overrides):
        params = {**filters, 'page': page}
        params.update(overrides)
        return '&'.join(f'{k}={v}' for k, v in params.items() if v)

    return render_template(
        'admin/charge_history.html',
        history=history,
        filters=filters,
        page=page,
        per_page=PER_PAGE,
        total_pages=total_pages,
        total_sessions=total_sessions,
        total_energy=total_energy,
        unique_users=unique_users,
        unique_stations=unique_stations,
        station_list=station_list,
        page_energy=page_energy,
        build_query=build_query,
    )


@admin_bp.route('/charge_history/export')
@login_required
@role_required('SuperAdmin', 'Admin_orange', 'Admin_white', 'Admin', 'admin')
def export_charge_history():
    q = request.args.get('q', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    station = request.args.get('station', '').strip()

    query = ChargeHistory.query

    if date_from:
        try:
            query = query.filter(ChargeHistory.start_time >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(ChargeHistory.start_time <= dt_to)
        except ValueError:
            pass
    if station:
        query = query.filter(ChargeHistory.charge_point_id == station)
    if q:
        like = f'%{q}%'
        matching_user_ids = [
            c.user_id for c in CustomerUser.query.filter(
                db.or_(CustomerUser.first_name.ilike(like), CustomerUser.last_name.ilike(like))
            ).all()
        ]
        query = query.filter(
            db.or_(
                ChargeHistory.selected_plate.ilike(like),
                ChargeHistory.charge_point_id.ilike(like),
                ChargeHistory.user_id.in_(matching_user_ids)
            )
        )

    rows = query.order_by(ChargeHistory.start_time.desc()).all()
    user_map = {c.user_id: c for c in CustomerUser.query.all()}

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        'ลำดับ', 'ชื่อ', 'นามสกุล', 'หน่วยงาน',
        'ทะเบียนรถ', 'สถานีชาร์จ', 'Connector',
        'Transaction ID', 'เวลาเริ่ม', 'เวลาสิ้นสุด',
        'ระยะเวลา (นาที)', 'พลังงาน (kWh)'
    ])
    for i, r in enumerate(rows, 1):
        cust = user_map.get(r.user_id)
        if r.start_time and r.stop_time:
            duration = round((r.stop_time - r.start_time).total_seconds() / 60, 1)
        else:
            duration = ''
        writer.writerow([
            i,
            cust.first_name if cust else '',
            cust.last_name if cust else '',
            cust.department if cust else '',
            r.selected_plate or '',
            r.charge_point_id or '',
            r.connector_id or '',
            r.transaction_id or '',
            r.start_time.strftime('%Y-%m-%d %H:%M') if r.start_time else '',
            r.stop_time.strftime('%Y-%m-%d %H:%M') if r.stop_time else '',
            duration,
            round(r.energy_used or 0, 3),
        ])

    buf.seek(0)
    filename = f"charge_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        '﻿' + buf.getvalue(),  # BOM สำหรับ Excel ภาษาไทย
        mimetype='text/csv; charset=utf-8-sig',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# ─── Dev-only audit log (URL ไม่อยู่บน navbar — เฉพาะ dev ที่รู้ key) ───

_DEV_KEY_ENV = 'DEV_LOG_KEY'
_DEV_AUTH_SESSION = '_dev_log_auth'

@admin_bp.route('/_sys/auditlog')
@login_required
def dev_auditlog():
    dev_key = os.getenv(_DEV_KEY_ENV, '')
    # ตรวจสอบ key ครั้งแรก แล้วเก็บใน flask session
    from flask import session as flask_session
    provided = request.args.get('ak', '')
    if provided:
        if not dev_key or provided != dev_key:
            return Response('Forbidden', status=403)
        flask_session[_DEV_AUTH_SESSION] = True
    elif not flask_session.get(_DEV_AUTH_SESSION):
        return Response('Forbidden', status=403)

    page = max(1, request.args.get('page', 1, type=int))
    action_filter = request.args.get('action', '').strip()
    user_filter = request.args.get('user', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()

    LOG_PER_PAGE = 100
    query = AdminLog.query

    if action_filter:
        query = query.filter(AdminLog.action == action_filter)
    if user_filter:
        query = query.filter(AdminLog.username.ilike(f'%{user_filter}%'))
    if date_from:
        try:
            query = query.filter(AdminLog.timestamp >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            query = query.filter(AdminLog.timestamp <= dt_to)
        except ValueError:
            pass

    query = query.order_by(AdminLog.timestamp.desc())
    total = query.count()
    total_pages = max(1, (total + LOG_PER_PAGE - 1) // LOG_PER_PAGE)
    page = min(page, total_pages)
    logs = query.offset((page - 1) * LOG_PER_PAGE).limit(LOG_PER_PAGE).all()

    action_list = [row[0] for row in db.session.query(AdminLog.action).distinct().order_by(AdminLog.action).all()]

    filters = {'action': action_filter, 'user': user_filter, 'date_from': date_from, 'date_to': date_to}

    def build_query(**overrides):
        params = {**filters, 'page': page}
        params.update(overrides)
        return '&'.join(f'{k}={v}' for k, v in params.items() if v not in (None, ''))

    return render_template(
        'admin/dev_logs.html',
        logs=logs,
        filters=filters,
        page=page,
        per_page=LOG_PER_PAGE,
        total=total,
        total_pages=total_pages,
        action_list=action_list,
        build_query=build_query,
    )


@admin_bp.route('/_sys/auditlog/export')
@login_required
def dev_auditlog_export():
    from flask import session as flask_session
    dev_key = os.getenv(_DEV_KEY_ENV, '')
    provided = request.args.get('ak', '')
    if provided:
        if not dev_key or provided != dev_key:
            return Response('Forbidden', status=403)
        flask_session[_DEV_AUTH_SESSION] = True
    elif not flask_session.get(_DEV_AUTH_SESSION):
        return Response('Forbidden', status=403)

    logs = AdminLog.query.order_by(AdminLog.timestamp.desc()).all()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(['timestamp', 'username', 'role', 'action', 'detail', 'ip_address', 'user_agent'])
    for log in logs:
        writer.writerow([
            log.timestamp.strftime('%Y-%m-%d %H:%M:%S') if log.timestamp else '',
            log.username, log.role or '', log.action,
            log.detail or '', log.ip_address or '', log.user_agent or '',
        ])
    buf.seek(0)
    filename = f"auditlog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return Response(
        '﻿' + buf.getvalue(),
        mimetype='text/csv; charset=utf-8-sig',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


# ─── Notify Email CRUD (SuperAdmin only) ───

from app.models.notify_email import DRIVER_TYPES

@admin_bp.route('/notify-emails')
@login_required
@role_required('SuperAdmin')
def notify_emails():
    entries = NotifyEmail.query.order_by(NotifyEmail.driver_type, NotifyEmail.id).all()
    grouped = {dt: [] for dt in DRIVER_TYPES}
    for e in entries:
        if e.driver_type in grouped:
            grouped[e.driver_type].append(e)
        else:
            grouped.setdefault(e.driver_type, []).append(e)
    return render_template('admin/notify_emails.html', grouped=grouped, driver_types=DRIVER_TYPES)


@admin_bp.route('/notify-emails/add', methods=['POST'])
@login_required
@role_required('SuperAdmin')
def notify_email_add():
    driver_type = (request.form.get('driver_type') or '').strip()
    email = (request.form.get('email') or '').strip().lower()
    label = (request.form.get('label') or '').strip()

    if not driver_type or driver_type not in DRIVER_TYPES:
        flash('ประเภทผู้ขับรถไม่ถูกต้อง', 'danger')
        return redirect(url_for('admin_bp.notify_emails'))
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        flash('รูปแบบ email ไม่ถูกต้อง', 'danger')
        return redirect(url_for('admin_bp.notify_emails'))

    exists = NotifyEmail.query.filter_by(driver_type=driver_type, email=email).first()
    if exists:
        flash(f'{email} มีอยู่แล้วสำหรับประเภทนี้', 'warning')
        return redirect(url_for('admin_bp.notify_emails'))

    entry = NotifyEmail(driver_type=driver_type, email=email, label=label or None)
    db.session.add(entry)
    db.session.commit()
    log_action('ADD_NOTIFY_EMAIL', detail=f'driver_type={driver_type} email={email}')
    flash(f'เพิ่ม {email} เรียบร้อยแล้ว', 'success')
    return redirect(url_for('admin_bp.notify_emails'))


@admin_bp.route('/notify-emails/<int:entry_id>/edit', methods=['POST'])
@login_required
@role_required('SuperAdmin')
def notify_email_edit(entry_id):
    entry = NotifyEmail.query.get_or_404(entry_id)
    new_email = (request.form.get('email') or '').strip().lower()
    new_label = (request.form.get('label') or '').strip()
    new_driver_type = (request.form.get('driver_type') or '').strip()

    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', new_email):
        flash('รูปแบบ email ไม่ถูกต้อง', 'danger')
        return redirect(url_for('admin_bp.notify_emails'))
    if new_driver_type not in DRIVER_TYPES:
        flash('ประเภทผู้ขับรถไม่ถูกต้อง', 'danger')
        return redirect(url_for('admin_bp.notify_emails'))

    duplicate = NotifyEmail.query.filter(
        NotifyEmail.driver_type == new_driver_type,
        NotifyEmail.email == new_email,
        NotifyEmail.id != entry_id
    ).first()
    if duplicate:
        flash(f'{new_email} มีอยู่แล้วสำหรับประเภทนี้', 'warning')
        return redirect(url_for('admin_bp.notify_emails'))

    log_action('EDIT_NOTIFY_EMAIL', detail=f'id={entry_id} {entry.email}->{new_email} {entry.driver_type}->{new_driver_type}')
    entry.email = new_email
    entry.label = new_label or None
    entry.driver_type = new_driver_type
    db.session.commit()
    flash('แก้ไขเรียบร้อยแล้ว', 'success')
    return redirect(url_for('admin_bp.notify_emails'))


@admin_bp.route('/notify-emails/<int:entry_id>/delete', methods=['POST'])
@login_required
@role_required('SuperAdmin')
def notify_email_delete(entry_id):
    entry = NotifyEmail.query.get_or_404(entry_id)
    log_action('DELETE_NOTIFY_EMAIL', detail=f'id={entry_id} driver_type={entry.driver_type} email={entry.email}')
    db.session.delete(entry)
    db.session.commit()
    flash(f'ลบ {entry.email} เรียบร้อยแล้ว', 'success')
    return redirect(url_for('admin_bp.notify_emails'))