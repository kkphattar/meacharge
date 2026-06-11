# Deploy ขึ้น DigitalOcean (Droplet + Docker Compose + GitHub Actions)

ขั้นตอน 1-6 ทำได้ทันทีโดย**ไม่ต้องมี domain**: รันระบบผ่าน IP ตรงๆ ก่อน
ส่วน domain/SSL/LINE webhook (ขั้นตอน 7-9) ค่อยทำทีหลังเมื่อมี domain พร้อม

## 1. สร้าง Droplet
1. สร้าง Droplet ใหม่ (แนะนำ Ubuntu 22.04 LTS, ขนาดอย่างน้อย 1 vCPU / 1GB RAM)
2. เพิ่ม SSH key ของคุณตอนสร้าง Droplet
3. จด IP address ของ Droplet ไว้

## 2. ติดตั้ง Docker บน Droplet
SSH เข้า Droplet แล้วรัน:
```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
```
(Docker Compose v2 มาพร้อมกับ `docker compose` แล้วในการติดตั้งล่าสุด)

## 3. Clone repo
```bash
mkdir -p /opt/line2charge && cd /opt/line2charge
git clone https://github.com/kkphattar/meacharge.git .
```

## 4. ตั้งค่า .env
```bash
cp .env.example .env
nano .env
```
กรอกค่าจริงทั้งหมด (mail, LINE channel, OCPP server, secret_key เป็นต้น)
- `database_url` ถ้าใช้ SQLite ปล่อยเป็น `sqlite:///db.sqlite3` ได้ (ไฟล์จะอยู่ใน `instance/` ซึ่ง mount เป็น volume แล้ว)
- `REDIS_HOST=redis` (ชื่อ service ใน docker-compose ไม่ใช่ `localhost`)
- `web_url` ใส่ `http://<DROPLET_IP>` ไปก่อน แล้วค่อยเปลี่ยนเป็น `https://yourdomain.com` ในขั้นตอนที่ 8

## 5. รันระบบครั้งแรก (HTTP ผ่าน IP)
config `nginx/conf.d/app.conf` เริ่มต้นเป็น HTTP-only อยู่แล้ว (ใช้ได้แม้ยังไม่มี domain — เพียงแต่ค่า `server_name` จะไม่ตรง แต่ nginx ยังรับ request ได้ตามปกติ):
```bash
docker compose up -d
```
ทดสอบเข้าผ่าน `http://<DROPLET_IP>`

## 6. ตั้งค่า GitHub Actions สำหรับ auto-deploy
ไปที่ repo GitHub > Settings > Secrets and variables > Actions แล้วเพิ่ม secrets:

| Secret | ค่า |
|---|---|
| `DEPLOY_HOST` | IP ของ Droplet |
| `DEPLOY_USER` | ชื่อ user สำหรับ SSH (เช่น `root`) |
| `DEPLOY_SSH_KEY` | private key ของ SSH ที่ใช้เข้า Droplet ได้ (private key ทั้งไฟล์) |
| `DEPLOY_PATH` | path ของ repo บน Droplet เช่น `/opt/line2charge` |

หลังตั้งค่าเสร็จ ทุกครั้งที่ push เข้า branch `main` จะมีการ SSH เข้า Droplet, `git pull`, build image ใหม่ และ restart container อัตโนมัติ (ดู `.github/workflows/deploy.yml`)

> **หมายเหตุ:** ไฟล์ `.env` ไม่ได้อยู่ใน git (ถูก gitignore) ดังนั้นต้องแก้ไขบน Droplet โดยตรงเมื่อมีการเปลี่ยน config/credentials

---

## เมื่อมี domain แล้ว ทำขั้นตอนต่อไปนี้

## 7. ตั้งค่า DNS
ที่ผู้ให้บริการ domain ของคุณ ให้เพิ่ม A record ชี้ไปที่ IP ของ Droplet:
```
A    yourdomain.com    -> <DROPLET_IP>
```
รอ DNS propagate (ตรวจสอบด้วย `nslookup yourdomain.com`)

อัปเดต `.env` บน Droplet: เปลี่ยน `web_url=https://yourdomain.com` แล้ว `docker compose restart web`

## 8. ขอ SSL certificate (Let's Encrypt) และสลับเป็น HTTPS
แก้ `DOMAIN_NAME` ใน config ให้เป็นโดเมนจริง:
```bash
sed -i "s/DOMAIN_NAME/yourdomain.com/g" nginx/conf.d/app.conf
docker compose restart nginx
```

ขอ certificate:
```bash
docker compose run --rm certbot certonly --webroot \
  -w /var/www/certbot \
  -d yourdomain.com \
  --email your-email@example.com --agree-tos --no-eff-email
```

สลับเป็น config แบบ HTTPS:
```bash
cp nginx/conf.d/app-ssl.conf nginx/conf.d/app.conf
sed -i "s/DOMAIN_NAME/yourdomain.com/g" nginx/conf.d/app.conf
docker compose up -d
docker compose exec nginx nginx -s reload
```

ตอนนี้เว็บควรเข้าถึงได้ผ่าน `https://yourdomain.com` แล้ว และ `certbot` container จะต่ออายุ certificate ให้อัตโนมัติทุก 12 ชั่วโมง

## 9. ตั้งค่า LINE webhook
ไปที่ LINE Developers Console แล้วตั้ง Webhook URL เป็น `https://yourdomain.com/<line_webhook_path>`

---

## คำสั่งที่ใช้บ่อย
```bash
# ดู log
docker compose logs -f web

# restart service
docker compose restart web

# สร้าง admin user แรก
docker compose exec web python create_admin.py
```

---

## Debug บน cloud server ผ่าน VS Code (เหมือนรัน docker compose dev แบบ local)

ใช้ extension **Remote - SSH** เพื่อให้ VS Code เปิดโฟลเดอร์โปรเจกต์บน Droplet โดยตรง แล้ว debug ได้เหมือนเครื่อง local:

1. ติดตั้ง extension "Remote - SSH" ใน VS Code
2. กด `Ctrl+Shift+P` > `Remote-SSH: Connect to Host` > ใส่ `user@<DROPLET_IP>`
3. เมื่อเชื่อมต่อแล้ว เปิดโฟลเดอร์ `/opt/line2charge` (หน้าต่าง VS Code นี้ตอนนี้ทำงาน "บน" Droplet แล้ว)
4. เปิด terminal ใน VS Code (จะเป็น terminal ของ Droplet) แล้วรัน:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.dev.yml up
   ```
   (ตั้ง `DEBUGPY_ENABLE=1` ใน `docker-compose.dev.yml` หรือผ่าน `.env` เพื่อให้ debugpy listen ที่ port 5678)
5. ใช้ launch config ที่มีอยู่แล้วใน `.vscode/launch.json` ชื่อ **"Docker: Attach to Flask"** (`connect: localhost:5678`) — VS Code Remote-SSH จะ forward port 5678 จาก Droplet มาให้อัตโนมัติ ไม่ต้องตั้ง SSH tunnel เอง
6. กด F5 เลือก "Docker: Attach to Flask" — ตั้ง breakpoint ในโค้ดได้ตามปกติ

> **ข้อควรระวัง:** อย่ารัน `docker-compose.dev.yml` (ที่เปิด debug/FLASK_DEBUG) ทับ container การใช้งานจริงบน production — ถ้า Droplet นี้เป็น production server ให้ใช้ Droplet/Containers แยกสำหรับ debug หรือ stop service จริงชั่วคราวก่อน
