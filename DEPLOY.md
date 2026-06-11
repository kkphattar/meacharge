# Deploy ขึ้น DigitalOcean (Droplet + Docker Compose + GitHub Actions)

## 1. สร้าง Droplet
1. สร้าง Droplet ใหม่ (แนะนำ Ubuntu 22.04 LTS, ขนาดอย่างน้อย 1 vCPU / 1GB RAM)
2. เพิ่ม SSH key ของคุณตอนสร้าง Droplet
3. จด IP address ของ Droplet ไว้

## 2. ตั้งค่า DNS
ที่ผู้ให้บริการ domain ของคุณ ให้เพิ่ม A record ชี้ไปที่ IP ของ Droplet:
```
A    yourdomain.com    -> <DROPLET_IP>
```
รอ DNS propagate (ตรวจสอบด้วย `nslookup yourdomain.com`)

## 3. ติดตั้ง Docker บน Droplet
SSH เข้า Droplet แล้วรัน:
```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
```
(Docker Compose v2 มาพร้อมกับ `docker compose` แล้วในการติดตั้งล่าสุด)

## 4. Clone repo
```bash
mkdir -p /opt/line2charge && cd /opt/line2charge
git clone https://github.com/kkphattar/meacharge.git .
```

## 5. ตั้งค่า .env
```bash
cp .env.example .env
nano .env
```
กรอกค่าจริงทั้งหมด (mail, LINE channel, OCPP server, secret_key เป็นต้น)
- `web_url` ให้ตั้งเป็น `https://yourdomain.com`
- `database_url` ถ้าใช้ SQLite ปล่อยเป็น `sqlite:///db.sqlite3` ได้ (ไฟล์จะอยู่ใน `instance/` ซึ่ง mount เป็น volume แล้ว)

## 6. ขอ SSL certificate (Let's Encrypt) ครั้งแรก
ไฟล์ `nginx/conf.d/app.conf` เริ่มต้นเป็น HTTP-only (สำหรับ ACME challenge) อยู่แล้ว ให้แก้ `DOMAIN_NAME` เป็นโดเมนจริงก่อน:
```bash
sed -i "s/DOMAIN_NAME/yourdomain.com/g" nginx/conf.d/app.conf
```

สั่งสร้าง container ขึ้นมาก่อน (ยังไม่มี cert):
```bash
docker compose up -d redis web nginx
```

ขอ certificate:
```bash
docker compose run --rm certbot certonly --webroot \
  -w /var/www/certbot \
  -d yourdomain.com \
  --email your-email@example.com --agree-tos --no-eff-email
```

## 7. สลับเป็น config แบบ HTTPS
```bash
cp nginx/conf.d/app-ssl.conf nginx/conf.d/app.conf
sed -i "s/DOMAIN_NAME/yourdomain.com/g" nginx/conf.d/app.conf
docker compose up -d
docker compose exec nginx nginx -s reload
```

ตอนนี้เว็บควรเข้าถึงได้ผ่าน `https://yourdomain.com` แล้ว และ `certbot` container จะต่ออายุ certificate ให้อัตโนมัติทุก 12 ชั่วโมง

## 8. ตั้งค่า LINE webhook
ไปที่ LINE Developers Console แล้วตั้ง Webhook URL เป็น `https://yourdomain.com/<line_webhook_path>`

## 9. ตั้งค่า GitHub Actions สำหรับ auto-deploy
ไปที่ repo GitHub > Settings > Secrets and variables > Actions แล้วเพิ่ม secrets:

| Secret | ค่า |
|---|---|
| `DEPLOY_HOST` | IP ของ Droplet |
| `DEPLOY_USER` | ชื่อ user สำหรับ SSH (เช่น `root`) |
| `DEPLOY_SSH_KEY` | private key ของ SSH ที่ใช้เข้า Droplet ได้ (private key ทั้งไฟล์) |
| `DEPLOY_PATH` | path ของ repo บน Droplet เช่น `/opt/line2charge` |

หลังตั้งค่าเสร็จ ทุกครั้งที่ push เข้า branch `main` จะมีการ SSH เข้า Droplet, `git pull`, build image ใหม่ และ restart container อัตโนมัติ (ดู `.github/workflows/deploy.yml`)

> **หมายเหตุ:** ไฟล์ `.env` ไม่ได้อยู่ใน git (ถูก gitignore) ดังนั้นต้องแก้ไขบน Droplet โดยตรงเมื่อมีการเปลี่ยน config/credentials

## คำสั่งที่ใช้บ่อย
```bash
# ดู log
docker compose logs -f web

# restart service
docker compose restart web

# สร้าง admin user แรก
docker compose exec web python create_admin.py
```
