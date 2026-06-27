"""
File storage service — local / S3 / MinIO backends.

STORAGE_BACKEND env var selects the backend (default: local).
All backends return a public URL string.
"""
import os
import secrets
from flask import current_app
from app.extensions import log

_ALLOWED_MIME_TYPES = {
    # Images
    "image/jpeg", "image/png", "image/gif", "image/webp",
    # Documents
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain", "text/csv",
}


def allowed_file(content_type: str) -> bool:
    return content_type in _ALLOWED_MIME_TYPES


def upload_file(file_obj, path: str, content_type: str) -> str:
    """
    Upload file_obj (file-like) to configured storage backend.
    path: desired storage path e.g. 'employees/EMP001/docs/resume.pdf'
    Returns a publicly accessible URL.
    """
    if not allowed_file(content_type):
        raise ValueError(f"File type '{content_type}' is not allowed")

    safe_path = _randomize_path(path)
    backend = current_app.config.get("STORAGE_BACKEND", "local")

    if backend == "s3":
        return _s3_upload(file_obj, safe_path, content_type)
    if backend == "minio":
        return _minio_upload(file_obj, safe_path, content_type)
    return _local_upload(file_obj, safe_path)


def _randomize_path(path: str) -> str:
    """Insert a random token before the filename to prevent guessing."""
    head, tail = os.path.split(path)
    name, ext = os.path.splitext(tail)
    token = secrets.token_hex(8)
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_")[:60]
    return os.path.join(head, f"{safe_name}_{token}{ext}").replace("\\", "/")


def _local_upload(file_obj, path: str) -> str:
    base_dir = current_app.config.get("STORAGE_LOCAL_PATH", "./data/uploads")
    full_path = os.path.join(base_dir, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    file_obj.save(full_path)
    log.info("local_upload", path=path)
    frontend_url = current_app.config.get("FRONTEND_URL", "http://localhost:5000")
    return f"{frontend_url}/uploads/{path}"


def _s3_upload(file_obj, path: str, content_type: str) -> str:
    import boto3
    bucket = current_app.config["AWS_BUCKET"]
    region = current_app.config.get("AWS_REGION", "ap-south-1")
    client = boto3.client(
        "s3",
        aws_access_key_id=current_app.config["AWS_ACCESS_KEY"],
        aws_secret_access_key=current_app.config["AWS_SECRET_KEY"],
        region_name=region,
    )
    client.upload_fileobj(
        file_obj, bucket, path,
        ExtraArgs={"ContentType": content_type, "ACL": "public-read"},
    )
    log.info("s3_upload", bucket=bucket, path=path)
    return f"https://{bucket}.s3.{region}.amazonaws.com/{path}"


def _minio_upload(file_obj, path: str, content_type: str) -> str:
    from minio import Minio
    endpoint = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
    access_key = os.environ.get("MINIO_ACCESS_KEY") or current_app.config.get("AWS_ACCESS_KEY", "")
    secret_key = os.environ.get("MINIO_SECRET_KEY") or current_app.config.get("AWS_SECRET_KEY", "")
    bucket = os.environ.get("MINIO_BUCKET") or current_app.config.get("AWS_BUCKET", "atlon-hrms")
    secure = os.environ.get("MINIO_SECURE", "false").lower() == "true"

    client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    data = file_obj.read()
    from io import BytesIO
    client.put_object(bucket, path, BytesIO(data), length=len(data), content_type=content_type)
    log.info("minio_upload", endpoint=endpoint, bucket=bucket, path=path)
    scheme = "https" if secure else "http"
    return f"{scheme}://{endpoint}/{bucket}/{path}"
