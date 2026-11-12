"""
Lambda #3: clasificador-resultado
Consulta el estado y resultado de clasificacion de una imagen en Amazon DynamoDB.
Evento: Invocado via API Gateway (GET /resultado?id=...)
"""
import json
import logging
import os
from decimal import Decimal

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
TABLE = os.environ.get("TABLE", "clasificador-residuos")
ALLOWED_ORIGIN = os.environ.get("ALLOWED_ORIGIN", "*")

CORS = {
    "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token",
    "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
    "Content-Type": "application/json",
}


def _json_default(obj):
    if isinstance(obj, Decimal):
        return int(obj) if obj % 1 == 0 else float(obj)
    return str(obj)


def _resp(code, body):
    return {
        "statusCode": code,
        "headers": CORS,
        "body": json.dumps(body, default=_json_default, ensure_ascii=False),
    }


def lambda_handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _resp(200, {"ok": True})

    imagen_id = (event.get("queryStringParameters") or {}).get("id", "").strip()
    if not imagen_id:
        return _resp(400, {"error": "Falta el parametro 'id' en la consulta."})

    try:
        res = dynamodb.Table(TABLE).get_item(Key={"imagen_id": imagen_id})
        item = res.get("Item")
    except (BotoCoreError, ClientError) as exc:
        logger.exception("Error consultando DynamoDB para imagen_id=%s", imagen_id)
        return _resp(500, {"error": "Error al consultar la base de datos.", "detalle": str(exc)})

    if not item:
        return _resp(200, {"estado": "procesando", "imagen_id": imagen_id})

    estado = item.get("estado", "listo")
    if estado == "error":
        return _resp(200, item)

    return _resp(200, {**item, "estado": "listo"})


# Alias para compatibilidad con handler personalizado
resultado = lambda_handler
