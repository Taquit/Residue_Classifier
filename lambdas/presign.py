"""
Lambda #1: clasificador-presign
Genera una URL prefirmada de Amazon S3 para subir la fotografia del residuo.
Evento: Invocado via API Gateway (POST /subir)
"""
import json
import logging
import os
import uuid

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client("s3")
BUCKET = os.environ.get("BUCKET", "")

CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token",
    "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
    "Content-Type": "application/json",
}

CONTENT_TYPES_PERMITIDOS = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
}


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": CORS,
        "body": json.dumps(body, ensure_ascii=False),
    }


def _parse_body(event):
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body)
    except (ValueError, TypeError):
        return {}


def lambda_handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _resp(200, {"ok": True})

    if not BUCKET:
        logger.error("La variable de entorno BUCKET no esta configurada.")
        return _resp(500, {"error": "Configuracion incompleta del servidor (falta BUCKET)."})

    body = _parse_body(event)
    qs = event.get("queryStringParameters") or {}
    content_type = (
        body.get("content_type")
        or qs.get("content_type")
        or "image/jpeg"
    ).strip().lower()

    if content_type not in CONTENT_TYPES_PERMITIDOS:
        return _resp(
            400,
            {
                "error": f"Formato no soportado ({content_type}). Usa JPEG o PNG.",
                "formatos_permitidos": list(CONTENT_TYPES_PERMITIDOS.keys()),
            },
        )

    ext = CONTENT_TYPES_PERMITIDOS[content_type]
    content_type_firma = "image/jpeg" if ext == "jpg" else "image/png"
    imagen_id = str(uuid.uuid4())
    key = f"uploads/{imagen_id}.{ext}"

    try:
        url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": BUCKET,
                "Key": key,
                "ContentType": content_type_firma,
            },
            ExpiresIn=300,
        )
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Error generando URL prefirmada para S3")
        return _resp(500, {"error": "No se pudo generar la URL de subida.", "detalle": str(exc)})

    return _resp(
        200,
        {
            "imagen_id": imagen_id,
            "upload_url": url,
            "content_type": content_type_firma,
            "s3_key": key,
        },
    )


# Alias para compatibilidad con handler personalizado
presign = lambda_handler
