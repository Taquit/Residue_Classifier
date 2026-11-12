"""
Lambda #2: clasificador-analizar
Analiza la fotografia subida a S3 mediante Amazon Rekognition,
clasifica el tipo de residuo y guarda el resultado en Amazon DynamoDB.
Evento: Disparador S3 ObjectCreated en uploads/
"""
import logging
import os
import time
from decimal import Decimal
from urllib.parse import unquote_plus

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

rekognition = boto3.client("rekognition")
dynamodb = boto3.resource("dynamodb")

BUCKET = os.environ.get("BUCKET", "")
TABLE = os.environ.get("TABLE", "clasificador-residuos")
TTL_SECONDS = 86400  # 24 horas para limpieza automatica en DynamoDB

# Categorias y clasificacion de etiquetas
ORGANICO = {
    "Apple", "Fruit", "Food", "Banana", "Vegetable", "Produce", "Plant", "Leaf",
    "Bread", "Egg", "Orange", "Citrus Fruit", "Meat", "Peel", "Grain", "Pizza",
    "Flower", "Grass", "Salad", "Mushroom", "Berry", "Avocado", "Tomato",
    "Potato", "Carrot", "Onion", "Lemon", "Lime", "Melon", "Watermelon",
    "Grape", "Pineapple", "Mango", "Peach", "Pear", "Pastry", "Cake",
    "Sandwich", "Cheese", "Seafood", "Fish", "Chicken", "Noodle", "Pasta",
    "Rice", "Bean", "Nut", "Seed", "Herb", "Coffee Beans", "Tea",
}

RECICLABLE = {
    "Bottle", "Water Bottle", "Plastic Bottle", "Beer Bottle", "Wine Bottle",
    "Glass Bottle", "Can", "Tin", "Aluminium", "Aluminum Can", "Beverage Can",
    "Soda Can", "Cardboard", "Carton", "Milk Carton", "Box", "Paper",
    "Newspaper", "Magazine", "Book", "Document", "Glass", "Jar", "Mason Jar",
    "Paper Bag", "Plastic", "Metal", "Steel", "Foil", "jug", "Container",
}

NO_RECICLABLE = {
    "Styrofoam", "Foam", "Polystyrene", "Diaper", "Straw", "Drinking Straw",
    "Cigarette", "Chewing Gum", "Plastic Bag", "Garbage Bag", "Trash Bag",
    "Tissue", "Napkin", "Paper Towel", "Toilet Paper", "Wet Wipe",
    "Ceramics", "Pottery", "Porcelain", "Mirror", "Light Bulb",
    "Toothbrush", "Toothpaste", "Chip Bag", "Snack Wrapper", "Candy Wrapper",
    "Wrapper", "Foil Wrapper", "Disposable Cup", "Coffee Cup", "Paper Plate",
    "Plastic Cutlery", "Plastic Fork", "Plastic Spoon", "Plastic Knife",
    "Bandage", "Mask", "Glove", "Rubber", "Sponge", "Shoe", "Clothing",
}

MATERIALES_GENERICOS = {"Plastic", "Paper", "Cardboard", "Foil", "Metal", "Glass", "Container"}

BOTES = {
    "organico": "Bote ORGANICO (verde)",
    "reciclable": "Bote INORGANICO RECICLABLE (azul)",
    "no_reciclable": "Bote INORGANICO NO RECICLABLE (gris)",
}


def clasificar(labels):
    """
    Clasifica las etiquetas de Rekognition ponderando etiquetas directas y jerarquias padre,
    evitando que etiquetas genericas de material opaquen objetos no reciclables.
    """
    if not labels:
        return "no_reciclable", 0.0

    puntos = {"organico": 0.0, "reciclable": 0.0, "no_reciclable": 0.0}
    max_conf = {"organico": 0.0, "reciclable": 0.0, "no_reciclable": 0.0}

    nombres_directos = {lb.get("Name", "") for lb in labels}
    hay_no_reciclable_especifico = bool(nombres_directos & NO_RECICLABLE)

    for lb in labels:
        nombre = lb.get("Name", "")
        confianza = float(lb.get("Confidence", 0.0))
        padres = {p.get("Name", "") for p in lb.get("Parents", []) if p.get("Name")}

        if nombre in NO_RECICLABLE:
            puntos["no_reciclable"] += confianza * 1.8
            max_conf["no_reciclable"] = max(max_conf["no_reciclable"], confianza)
            continue

        if nombre in RECICLABLE:
            if hay_no_reciclable_especifico and nombre in MATERIALES_GENERICOS:
                factor = 0.2
            elif nombre in MATERIALES_GENERICOS:
                factor = 1.0
            else:
                factor = 1.5
            puntos["reciclable"] += confianza * factor
            max_conf["reciclable"] = max(max_conf["reciclable"], confianza)

        if nombre in ORGANICO:
            factor = 1.4 if nombre != "Food" else 1.1
            puntos["organico"] += confianza * factor
            max_conf["organico"] = max(max_conf["organico"], confianza)

        for p in padres - {nombre}:
            if p in NO_RECICLABLE:
                puntos["no_reciclable"] += confianza * 0.5
                max_conf["no_reciclable"] = max(max_conf["no_reciclable"], confianza * 0.85)
            elif p in RECICLABLE:
                if not (hay_no_reciclable_especifico and p in MATERIALES_GENERICOS):
                    puntos["reciclable"] += confianza * 0.35
                    max_conf["reciclable"] = max(max_conf["reciclable"], confianza * 0.8)
            elif p in ORGANICO:
                puntos["organico"] += confianza * 0.35
                max_conf["organico"] = max(max_conf["organico"], confianza * 0.8)

    total = sum(puntos.values())
    if total == 0:
        return "no_reciclable", 0.0

    categoria = max(puntos, key=puntos.get)
    proporcion = puntos[categoria] / total
    conf_base = max_conf[categoria] if max_conf[categoria] > 0 else 70.0

    confianza_final = round(min(99.9, conf_base * (0.55 + 0.45 * proporcion)), 1)
    return categoria, confianza_final


def _extraer_imagen_id(key):
    nombre_archivo = key.split("/")[-1]
    return nombre_archivo.rsplit(".", 1)[0] if "." in nombre_archivo else nombre_archivo


def _guardar_resultado(tabla, item):
    item["actualizado_en"] = int(time.time())
    item["ttl"] = int(time.time()) + TTL_SECONDS
    tabla.put_item(Item=item)


def lambda_handler(event, context):
    tabla = dynamodb.Table(TABLE)
    records = event.get("Records") or []
    procesados = 0
    errores = 0

    for rec in records:
        bucket = rec.get("s3", {}).get("bucket", {}).get("name") or BUCKET
        raw_key = rec.get("s3", {}).get("object", {}).get("key", "")
        if not raw_key:
            continue

        key = unquote_plus(raw_key)
        imagen_id = _extraer_imagen_id(key)

        try:
            r = rekognition.detect_labels(
                Image={"S3Object": {"Bucket": bucket, "Name": key}},
                MaxLabels=15,
                MinConfidence=70,
            )
            labels = r.get("Labels", [])
            categoria, confianza = clasificar(labels)

            _guardar_resultado(
                tabla,
                {
                    "imagen_id": imagen_id,
                    "estado": "listo",
                    "s3_key": key,
                    "categoria": categoria,
                    "bote": BOTES[categoria],
                    "confianza": Decimal(str(confianza)),
                    "etiquetas": [l["Name"] for l in labels],
                    "etiquetas_detalle": [
                        {
                            "nombre": l["Name"],
                            "confianza": Decimal(str(round(float(l.get("Confidence", 0.0)), 1))),
                        }
                        for l in labels
                    ],
                },
            )
            procesados += 1

        except (BotoCoreError, ClientError, Exception) as exc:
            errores += 1
            logger.exception("Error analizando imagen %s en bucket %s", key, bucket)
            try:
                _guardar_resultado(
                    tabla,
                    {
                        "imagen_id": imagen_id,
                        "estado": "error",
                        "s3_key": key,
                        "error": "No se pudo analizar la imagen. Verifica que sea un archivo JPG o PNG valido.",
                        "detalle_tecnico": str(exc),
                    },
                )
            except Exception:
                logger.exception("No se pudo registrar el estado de error en DynamoDB para %s", imagen_id)

    return {"ok": errores == 0, "procesados": procesados, "errores": errores}


# Alias para compatibilidad con handler personalizado
analizar = lambda_handler
