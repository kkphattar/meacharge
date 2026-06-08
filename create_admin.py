# create_admin.py

from app.factory import create_app
from app.models import db
from app.models.admin_user import AdminUser

def create_admin():
    app = create_app()

    with app.app_context():
        print("🔧 สร้างตารางฐานข้อมูล (ถ้ายังไม่มี)")
        db.create_all()  # 👈 สำคัญ!

        print("🛠️  สร้างผู้ดูแลระบบ (Admin)")
        # id = input("id: ").strip()        
        first_name = input("First Name: ").strip()
        last_name = input("Last Name: ").strip()
        email = input("📧 Email: ").strip()
        mea_id = input("MEA ID: ").strip()
        phone = input("Phone Number: ").strip()
        departments = input("Departments: ").strip()
        username = input("👤 Username: ").strip()
        password = input("🔒 Password: ").strip()
        role = input("role: ").strip()

        existing_user = AdminUser.query.filter_by(username=username).first()
        if existing_user:
            print(f"⚠️  ชื่อผู้ใช้งาน '{username}' มีอยู่แล้วในระบบ")
            return
        
        admin = AdminUser(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email,
            role=role,
            phone=phone,
            mea_id=mea_id,
            departments=departments
        )
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print("✅ ผู้ดูแลระบบถูกสร้างเรียบร้อยแล้ว")

if __name__ == '__main__':
    create_admin()
