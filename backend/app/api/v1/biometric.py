import uuid
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g, current_app
from app.extensions import db
from app.models import BiometricDevice, BiometricLog, Employee, Attendance, AttendanceStatus, AttendanceSource
from app.utils.auth import require_auth

biometric_bp = Blueprint("biometric", __name__)


@biometric_bp.route("/iclock/cdata", methods=["GET"])
def iclock_handshake():
    """ZKTeco iClock device handshake — returns server time and timezone."""
    import pytz
    from datetime import datetime
    tz = pytz.timezone("Asia/Kolkata")
    server_time = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")
    sn = request.args.get("SN", "")
    return f"GET OPTION FROM: {sn}\nATTSTAMPLIMIT=0\nOPTIMIZE=1\nServerVer=2.4.2-20110214\nTransFlag=TransData AttLog\nTimeZone=8\nSYNC=True\nDateTime={server_time}\n", 200, {"Content-Type": "text/plain"}


@biometric_bp.route("/iclock/cdata", methods=["POST"])
def iclock_push():
    """Receive raw attendance data pushed by ZKTeco device."""
    sn = request.args.get("SN", "")
    table = request.args.get("table", "")
    body = request.get_data(as_text=True) or ""

    if table == "ATTLOG":
        lines = [l.strip() for l in body.strip().split("\n") if l.strip()]
        for line in lines:
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            emp_number = parts[0].strip()
            punch_time_str = parts[1].strip()
            punch_type = int(parts[2]) if len(parts) > 2 else 0

            try:
                punch_time = datetime.strptime(punch_time_str, "%Y-%m-%d %H:%M:%S")
                punch_time = punch_time.replace(tzinfo=timezone.utc)
            except ValueError:
                continue

            log = BiometricLog(
                id=uuid.uuid4(),
                device_id=sn,
                employee_number=emp_number,
                punch_time=punch_time,
                punch_type=punch_type,
                raw_data={"line": line},
                is_processed=False,
            )
            db.session.add(log)

        db.session.commit()
        _process_biometric_logs(sn)

    return "OK", 200, {"Content-Type": "text/plain"}


def _process_biometric_logs(device_id: str = None):
    """Process pending biometric logs into attendance records."""
    q = BiometricLog.query.filter_by(is_processed=False)
    if device_id:
        q = q.filter_by(device_id=device_id)
    logs = q.order_by(BiometricLog.punch_time).all()

    device_tenant_map = {}
    for log in logs:
        if log.device_id not in device_tenant_map:
            dev = BiometricDevice.query.filter_by(serial_number=log.device_id).first()
            device_tenant_map[log.device_id] = str(dev.tenant_id) if dev else None
        tenant_id = device_tenant_map.get(log.device_id)
        if not tenant_id:
            log.is_processed = True
            continue

        emp = Employee.query.filter_by(
            tenant_id=tenant_id,
            employee_number=log.employee_number,
            is_deleted=False
        ).first()
        if not emp:
            log.is_processed = True
            continue

        att_date = log.punch_time.date()
        existing = Attendance.query.filter_by(
            tenant_id=tenant_id, employee_id=emp.id, date=att_date, is_deleted=False
        ).first()

        if not existing:
            att = Attendance(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                employee_id=emp.id,
                date=att_date,
                check_in=log.punch_time,
                check_in_source=AttendanceSource.BIOMETRIC,
                device_id=log.device_id,
                status=AttendanceStatus.PRESENT,
                biometric_log_id=str(log.id),
            )
            db.session.add(att)
        elif not existing.check_out and existing.check_in != log.punch_time:
            existing.check_out = log.punch_time
            existing.check_out_source = AttendanceSource.BIOMETRIC
            if existing.check_in:
                hours = (log.punch_time - existing.check_in).total_seconds() / 3600
                existing.working_hours = round(hours, 2)

        log.is_processed = True
        log.processed_at = datetime.now(timezone.utc)

    db.session.commit()


@biometric_bp.route("/iclock/getrequest", methods=["GET"])
def iclock_getrequest():
    return "OK", 200, {"Content-Type": "text/plain"}


@biometric_bp.route("/iclock/devicecmd", methods=["POST"])
def iclock_devicecmd():
    return "OK", 200, {"Content-Type": "text/plain"}


@biometric_bp.route("/manual-push", methods=["POST"])
@require_auth(roles=["hr_admin"])
def manual_push():
    """Manually trigger processing of pending biometric logs."""
    _process_biometric_logs()
    return jsonify({"message": "Biometric logs processed"})


@biometric_bp.route("/config", methods=["GET"])
@require_auth(roles=["hr_admin"])
def get_config():
    devices = BiometricDevice.query.filter_by(
        tenant_id=g.tenant_id, is_deleted=False
    ).all()
    return jsonify({
        "devices": [d.to_dict() for d in devices],
        "setup_instructions": {
            "protocol": "ZKTeco iClock HTTP Push",
            "server_ip": "your-server-ip",
            "port": 80,
            "push_url": "/api/biometric/iclock/cdata",
            "steps": [
                "1. Configure ZKTeco device to push to this server IP and port",
                "2. Set Server URL to: http://your-server/api/biometric/iclock/cdata",
                "3. Device will auto-sync attendance every 5 minutes",
            ]
        }
    })


@biometric_bp.route("/devices", methods=["POST"])
@require_auth(roles=["hr_admin"])
def register_device():
    data = request.get_json(silent=True) or {}
    device = BiometricDevice(
        id=uuid.uuid4(),
        tenant_id=g.tenant_id,
        serial_number=data.get("serial_number", "").strip(),
        name=data.get("name", "").strip(),
        model=data.get("model"),
        branch_id=data.get("branch_id"),
        ip_address=data.get("ip_address"),
        is_active=True,
    )
    db.session.add(device)
    db.session.commit()
    return jsonify({"device": device.to_dict()}), 201
