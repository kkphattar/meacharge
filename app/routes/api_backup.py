# api.py
from flask import Blueprint, jsonify, request, session, redirect, url_for
from app.models import CustomerUser, ChargeHistory, db
from dateutil import parser
import sys
import datetime
import json
import hashlib
import requests
import os
import pytz

api_bp = Blueprint('api', __name__)

utc_datetime = datetime.datetime.utcnow();
tz_bangkok = pytz.timezone('Asia/Bangkok')

username = os.getenv('username')
pwd = os.getenv('pwd')
ocppserver = os.getenv('ocppserver')
ocpphost = os.getenv('ocpphost')

# Mock database หรือ API response
mock_customer = {
    "user_id": "1234567890",
    "first_name": "สมชาย",
    "last_name": "ใจดี",
    "department": "ฝวจ.",
    "email": "somchai@example.com",
    "license_plate": "2กข5151",
    "credit_kwh": 10000,
    "verified": True
}

mock_charge_history = [
    {"datetime": "2025-07-01 10:30", "station": "EV001", "kwh": 15.2},
    {"datetime": "2025-07-05 14:10", "station": "EV002", "kwh": 8.6}
]

mock_status = {
    "charging": False,
    "meter_value": {
        "voltage": 220,
        "current": 15.5,
        "power": 3.3,
        "energy": 5.4
    }
}

@api_bp.route('/api/customer_info', methods=['GET'])
def get_customer_info():
    print("Fetching customer info for user_id:")
    return jsonify({
        "success": True,
        "data": {
            "first_name": mock_customer["first_name"],
            "last_name": mock_customer["last_name"],
            "full_name": f"{mock_customer['first_name']} {mock_customer['last_name']}",
            "department": mock_customer["department"],
            "email": mock_customer["email"],
            "license_plate": mock_customer["license_plate"],
            "verified": mock_customer["verified"],
        }
    })

@api_bp.route('/api/credit', methods=['GET'])
def get_credit():
    return jsonify({"success": True, "credit_kwh": mock_customer['credit_kwh']})


@api_bp.route('/api/history', methods=['GET'])
def get_charge_history():
    return jsonify({"success": True, "history": mock_charge_history})


@api_bp.route('/api/status', methods=['GET'])
def get_charging_status():
    return jsonify({"success": True, "status": mock_status})


@api_bp.route('/api/scan', methods=['POST'])
def scan_qr():
    data = request.get_json()
    qrcode = data.get("qrcode")
    if qrcode == "VALID_QR_123":
        return jsonify({"success": True, "message": "QR ถูกต้อง", "charger_id": "EV001"})
    else:
        return jsonify({"success": False, "message": "QR ไม่ถูกต้อง"}), 400


@api_bp.route('/api/map', methods=['GET'])
def get_map_data():
    return jsonify({"success": True, "locations": []})


@api_bp.route('/api/verify_status', methods=['GET'])
def get_verification_status():
    user_id = request.args.get("user_id")
    return jsonify({"success": True, "verified": mock_customer['verified']})


def md5_utf8(x):
    if isinstance(x, str):
        x = x.encode('utf-8')
    return hashlib.md5(x).hexdigest()

@api_bp.route('/api/remotestart', methods=['POST'])
def remotestart():
    data = request.get_json()  # รับข้อมูล JSON จาก body
    print("Received data:", data)
    realm = "EV";
    uri = "/EV/cmd/chargepoint/remoteStart/";
    method = "POST";
    nonce = utc_datetime.strftime("%Y-%m-%dT%H:%M:%SZ");
    HA1 = md5_utf8(username + ":" + realm + ":" + pwd);
    HA2 = md5_utf8(method + ":" + uri);
    response = md5_utf8(HA1 + ":" + nonce + ":" + HA2);
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "Accept": "application/json;charset=utf-8",
        "HOST": "ocppapi.measandbox.com",
        "Authorization": 'Digest username="' + username + '", realm="' + realm
                         + '", nonce="' + nonce + '", uri="' + uri
                         + '", algorithm=MD5, response="' + response + '"'
    }
    if 'qr' in session:
        qr = session['qr']
        cpid = qr.get('cpid', None)
        connid = qr.get('connid', None)
        connid = int(connid)
        card_id = session['token_id']
        selected_plate=session['selected_plate']
    if not cpid:
        print ("ChargePoint ID not found in session")
        return jsonify({"success": False, "message": "ChargePoint ID not found in session"}), 400
    if not connid:
        print ("Connector ID not found in session")
        return jsonify({"success": False, "message": "Connector ID not found in session"}), 400
    body = {
        "chargepoint_id" : cpid,
        "connector_id" : connid,
        "card_id": card_id
    }
    request_info = {
        "method": method,
        "headers": headers,
        "body": json.dumps(body)
    }
    print(f"QR received: {body}")
    try:
        res = requests.post(ocppserver + "/EV/cmd/chargepoint/remoteStart/", headers=headers, json=body)
        response_json = res.json()
        status_code = res.status_code
    except Exception as e:
        # กรณีเกิด error ในการเรียก API จริง
        response_json = {"error": str(e)}
        status_code = 500

    # รวม request info กับ response จาก API จริง ส่งกลับ frontend
    print(f"response: {response_json}")
    if status_code == 200:
        if response_json.get('code', 500) == 200:
            session['charging_session'] = True
        charging_data = {
            "cpid": cpid,
            "connid": connid,
            "card_id": body['card_id'],
            "selected_plate": selected_plate,
            "transaction_id": response_json.get('result', {}).get('transaction_id', None)
        }
        session['charging_data'] = charging_data
        print("Remote start successful :{charging_data}")
    return jsonify({
        "request": request_info,
        "response": response_json,
        "status_code": status_code
    }), status_code

@api_bp.route('/api/remotestop', methods=['GET'])
def remotestop():
    realm = "EV";
    uri = "/EV/cmd/chargepoint/remoteStop/";
    method = "POST";
    nonce = utc_datetime.strftime("%Y-%m-%dT%H:%M:%SZ");
    HA1 = md5_utf8(username + ":" + realm + ":" + pwd);
    HA2 = md5_utf8(method + ":" + uri);
    response = md5_utf8(HA1 + ":" + nonce + ":" + HA2);
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "Accept": "application/json;charset=utf-8",
        "HOST": "ocppapi.measandbox.com",
        "Authorization": 'Digest username="' + username + '", realm="' + realm
                         + '", nonce="' + nonce + '", uri="' + uri
                         + '", algorithm=MD5, response="' + response + '"'
    }
    # cpid = None
    # connid = None
    # transaction_id = None
    if 'charging_data' in session:
        charging_data = session['charging_data']
        cpid = charging_data.get('cpid', None)
        connid = charging_data.get('connid', None)
        transaction_id = charging_data.get('transaction_id', None)
        transaction_id = int(transaction_id) if transaction_id else None
    else:
        cpid = None
        connid = None
        transaction_id = None
    if not cpid:
        print ("ChargePoint ID not found in session")
        session['charging_session'] = False
        session.pop('charging_data', None)        
        return redirect(url_for('line_bp.customer_home')) 
        # return jsonify({"success": False, "message": "ChargePoint ID not found in session"}), 400
        
    if not transaction_id:
        print ("transaction_id not found in session")
        session['charging_session'] = False
        session.pop('charging_data', None)
        # return jsonify({"success": False, "message": "transaction_id not found in session"}), 400
        return redirect(url_for('line_bp.customer_home'))
    body = {
        "chargepoint_id" : cpid,
        "transaction_id" : transaction_id
        }
    request_info = {
        "method": method,
        "headers": headers,
        "body": json.dumps(body)
    }
    try:
        res = requests.post(ocppserver + "/EV/cmd/chargepoint/remoteStop/", headers=headers, json=body)
        response_json = res.json()
        status_code = res.status_code
    except Exception as e:
        # กรณีเกิด error ในการเรียก API จริง
        response_json = {"error": str(e)}
        status_code = 500
    
    start_time = response_json.get('result', {}).get('start_time', utc_datetime)
    start_time = parser.parse(start_time) if start_time else utc_datetime
    stop_time = response_json.get('result', {}).get('stop_time', utc_datetime)  
    stop_time = parser.parse(stop_time) if stop_time else utc_datetime

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=pytz.UTC)
    if stop_time.tzinfo is None:
        stop_time = stop_time.replace(tzinfo=pytz.UTC)

    # แปลงเป็น UTC+7
    start_time = start_time.astimezone(tz_bangkok)
    stop_time  = stop_time.astimezone(tz_bangkok)

    # รวม request info กับ response จาก API จริง ส่งกลับ frontend
    print(f"response: {response_json}")
    if response_json.get('code') == 200 or response_json.get('messages') == 'This transaction is already complete.':
        if response_json.get('code') == 200:
            charging_data['start_time'] = response_json.get('result', {}).get('start_time', utc_datetime)
            charging_data['stop_time'] = response_json.get('result', {}).get('stop_time', utc_datetime)
            charging_data['energy_used'] = response_json.get('result', {}).get('kWh', 0)
            charging_data['current'] = response_json.get('result', {}).get('amp', 0)
            charging_data['power'] = response_json.get('result', {}).get('kW', 0)
            session['charging_data'] = charging_data

            # บันทึกประวัติการชาร์จลงฐานข้อมูล
            charge_history = ChargeHistory(
                user_id=session.get('user_id', None),
                transaction_id=transaction_id,
                charge_point_id=charging_data.get('cpid', None),
                connector_id=charging_data.get('connid', None),
                start_time=start_time,
                stop_time=stop_time,
                energy_used=response_json.get('result', {}).get('kWh', 0),
                selected_plate=charging_data.get('selected_plate', None)
            )
            # สมมุติว่ามีฟังก์ชัน save_charge_history เพื่อบันทึกลงฐานข้อมูล
            db.session.add(charge_history)
            db.session.commit()

        session['charging_session'] = False
        session.pop('charging_data', None)
        return jsonify({
            "request": request_info,
            "response": response_json,
            "status_code": status_code
        }), status_code    
    else:
        print("Remote stop failed")
        return jsonify({
            "request": request_info,
            "response": response_json,
            "status_code": status_code
        }), status_code

    


@api_bp.route('/api/energyUsage')
def energyUsage():
    realm = "EV";
    uri = "/EV/get/energyUsage/transaction/";
    method = "POST";
    nonce = utc_datetime.strftime("%Y-%m-%dT%H:%M:%SZ");
    HA1 = md5_utf8(username + ":" + realm + ":" + pwd);
    HA2 = md5_utf8(method + ":" + uri);
    response = md5_utf8(HA1 + ":" + nonce + ":" + HA2);
    headers = {
        "Content-Type": "application/json;charset=utf-8",
        "Accept": "application/json;charset=utf-8",
        "HOST": "ocppapi.measandbox.com",
        "Authorization": 'Digest username="' + username + '", realm="' + realm
                         + '", nonce="' + nonce + '", uri="' + uri
                         + '", algorithm=MD5, response="' + response + '"'
    }
    if 'charging_data' in session:
        charging_data = session['charging_data']
        connid = charging_data.get('connid', None)
        transaction_id = charging_data.get('transaction_id', None)
        transaction_id = int(transaction_id) if transaction_id else None
        selected_plate=charging_data.get('selected_plate', None)
    if not transaction_id:
        print ("transaction_id not found in session")
        session['charging_session'] = False
        session.pop('charging_data', None)        
        return redirect(url_for('line_bp.customer_home')) 
        # return jsonify({"success": False, "message": "transaction_id not found in session"}), 400
    body = {
        "transaction_id": transaction_id
    }
    request_info = {
        "method": method,
        "headers": headers,
        "body": json.dumps(body)
    }
    try:
        res = requests.post(ocppserver + "/EV/get/energyUsage/transaction/", headers=headers, json=body)
        response_json = res.json()
        status_code = res.status_code
        
    except Exception as e:
        # กรณีเกิด error ในการเรียก API จริง
        response_json = {"error": str(e)}
        status_code = 500
    
    start_time = response_json.get('result', {}).get('start_time', utc_datetime)
    start_time = parser.parse(start_time) if start_time else utc_datetime
    stop_time = response_json.get('result', {}).get('stop_time', utc_datetime)  
    stop_time = parser.parse(stop_time) if stop_time else utc_datetime

    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=pytz.UTC)
    if stop_time.tzinfo is None:
        stop_time = stop_time.replace(tzinfo=pytz.UTC)

    # แปลงเป็น UTC+7
    start_time = start_time.astimezone(tz_bangkok)
    stop_time  = stop_time.astimezone(tz_bangkok)

    print(f"response: {response_json}")
    if response_json.get('result', {}).get('complete', True) == True:
        charging_data['start_time'] = response_json.get('result', {}).get('start_time', utc_datetime)
        charging_data['stop_time'] = response_json.get('result', {}).get('stop_time', utc_datetime)
        charging_data['energy_used'] = response_json.get('result', {}).get('kWh', 0)
        charging_data['current'] = response_json.get('result', {}).get('amp', 0)
        charging_data['power'] = response_json.get('result', {}).get('kW', 0)
        session['charging_data'] = charging_data

        # บันทึกประวัติการชาร์จลงฐานข้อมูล
        charge_history = ChargeHistory(
            user_id=session.get('user_id', None),
            transaction_id=transaction_id,
            charge_point_id=charging_data.get('cpid', None),
            connector_id=charging_data.get('connid', None),
            start_time=start_time,
            stop_time=stop_time,
            energy_used=response_json.get('result', {}).get('kWh', 0),
            selected_plate=selected_plate
        )
        # สมมุติว่ามีฟังก์ชัน save_charge_history เพื่อบันทึกลงฐานข้อมูล
        db.session.add(charge_history)
        db.session.commit()
        session['charging_session'] = False
        session.pop('charging_data', None)
        # รวม request info กับ response จาก API จริง ส่งกลับ frontend
        return jsonify({
            "request": request_info,
            "response": response_json,
            "status_code": status_code
        }), status_code
    else: 
        # charging_data = {
        #     "cpid": cpid,
        #     "connid": connid,
        #     "card_id": body['card_id'],
        #     "transaction_id": response_json.get('result', {}).get('transaction_id', None)
        # }

        return jsonify({
            "request": request_info,
            "response": response_json,
            "status_code": status_code
        }), status_code