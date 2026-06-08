const resultSpan = document.getElementById('result');
const readerDiv = document.getElementById('reader');
const startBtn = document.getElementById('startBtn');
const stopBtn = document.getElementById('stopBtn');
const cameraSelect = document.getElementById('cameraSelect');

let html5QrcodeScanner = null;
let currentCameraId = null;

// ดึงรายการกล้องที่มี
Html5Qrcode.getCameras().then(cameras => {
    if (cameras && cameras.length) {
        cameras.forEach(cam => {
            const opt = document.createElement('option');
            opt.value = cam.id;
            opt.text = cam.label || cam.id;
            cameraSelect.appendChild(opt);
        });
        currentCameraId = cameras[0].id;
    } else {
        const opt = document.createElement('option');
        opt.text = "No camera found";
        cameraSelect.appendChild(opt);
    }
}).catch(err => {
    console.warn("getCameras() error:", err);
});

// เมื่อเลือกกล้องเปลี่ยน currentCameraId
cameraSelect.addEventListener('change', (e) => {
    currentCameraId = e.target.value;
});

// เริ่มสแกน
startBtn.addEventListener('click', async () => {
    if (!currentCameraId) {
        alert("ไม่พบกล้อง");
        return;
    }

    startBtn.disabled = true;
    stopBtn.disabled = false;

    html5QrcodeScanner = new Html5Qrcode(/* element id */ "reader");

    const config = {
        fps: 10,
        qrbox: { width: 250, height: 250 }
    };

    try {
        await html5QrcodeScanner.start(
            { deviceId: { exact: currentCameraId } },
            config,
            onScanSuccess,
            onScanFailure
        );
    } catch (err) {
        console.error("Start failed:", err);
        startBtn.disabled = false;
        stopBtn.disabled = true;
    }
});

// หยุดสแกน
stopBtn.addEventListener('click', async () => {
    stopBtn.disabled = true;
    startBtn.disabled = false;
    if (html5QrcodeScanner) {
        try {
            await html5QrcodeScanner.stop();
            html5QrcodeScanner.clear();
            html5QrcodeScanner = null;
            resultSpan.innerText = "หยุดสแกน";
        } catch (err) {
            console.error("Stop error:", err);
        }
    }
});

function onScanSuccess(decodedText, decodedResult) {
    // แสดงผลทันที
    resultSpan.innerText = decodedText;

    // ส่งข้อมูลไป backend (Flask)
    fetch('/api/qr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ data: decodedText })
    })
    .then(r => r.json())
    .then(j => {
        console.log("Server response:", j);
        // สามารถแสดงข้อความเพิ่มเติมจาก server ได้
    })
    .catch(err => {
        console.error("Failed to send to server:", err);
    });

    // ถ้าต้องการให้หยุดหลังสแกนครั้งแรก:
    // html5QrcodeScanner.stop();
}

function onScanFailure(error) {
    // ฟังก์ชันนี้ถูกเรียกบ่อยๆ เมื่อแต่ละ frame ไม่พบ QR — ปกติจะไม่ต้องทำอะไร
    // console.debug("scan failure", error);
}
