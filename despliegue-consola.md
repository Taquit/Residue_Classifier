# Guia de Despliegue desde la Consola de AWS (Sin CloudFront)

Esta guia describe el proceso paso a paso para desplegar la arquitectura completa del Clasificador Inteligente de Residuos utilizando unicamente la Consola de Administracion de AWS, sirviendo el frontend directamente desde Amazon S3 mediante Static Website Hosting (sin CloudFront).

---

## Arquitectura de la Solucion

- **Base de Datos:** Amazon DynamoDB (tabla para almacenar resultados y etiquetas con expiracion TTL).
- **Almacenamiento de Fotos:** Amazon S3 (bucket privado con CORS para subidas directas via URL prefirmada).
- **Seguridad:** Rol de AWS IAM con politicas de menor privilegio para Lambda.
- **Logica de Negocio:** 3 Funciones AWS Lambda independientes (Python 3.12):
  - `clasificador-presign`: Codigo de `lambdas/presign.py` (POST /subir).
  - `clasificador-analizar`: Codigo de `lambdas/analizar.py` (Trigger S3 en `uploads/`).
  - `clasificador-resultado`: Codigo de `lambdas/resultado.py` (GET /resultado?id=...).
- **API:** Amazon API Gateway (REST API con proxy Lambda y CORS habilitado).
- **Frontend Web:** Amazon S3 con Alojamiento de Sitios Web Estaticos (acceso de lectura publico).

---

## Verificacion de AWS Free Tier (Cuentas Nuevas)

Toda esta arquitectura es **100% compatible con la capa gratuita de AWS (AWS Free Tier)** al crear una cuenta nueva:

- **AWS Lambda (Always Free - Permanente):** Incluye gratis 1,000,000 de invocaciones y 400,000 GB-segundos al mes de forma indefinida.
- **Amazon DynamoDB (Always Free - Permanente):** Incluye gratis 25 GB de almacenamiento, 25 RCU y 25 WCU al mes de forma indefinida **unicamente en modo Aprovisionado (Provisioned)**. Por ello, el Paso 1 configura 5 RCU y 5 WCU sin Auto Scaling (en lugar de modo On-Demand).
- **Amazon CloudWatch Logs (Always Free - Permanente):** Incluye gratis 5 GB de logs al mes.
- **Amazon Rekognition, Amazon S3 y API Gateway:**
  - **Cuentas nuevas (creadas desde el 15 de julio de 2025):** Cubiertos por los **hasta $200 USD en creditos** (6 meses) del **Free Plan** o **Paid Plan** ($100 USD al registrarse + hasta $100 USD al completar actividades iniciales). En el *Free Plan*, AWS bloquea cualquier cargo a tu tarjeta. Analizar 1,000 imagenes con `DetectLabels` consume solo $1.00 USD de ese credito gratuito.
  - **Cuentas Legacy (anteriores al 15 de julio de 2025):** Cubiertos durante los primeros 12 meses (1,000 imagenes/mes en Rekognition Grupo 2, 5 GB y 2,000 PUT en S3, y 1,000,000 de llamadas REST en API Gateway).

---

## Paso 1: Crear la Tabla en DynamoDB

1. Inicia sesion en la consola de AWS y ve al servicio **DynamoDB**.
2. Haz clic en **Crear tabla** (Create table).
3. Ingresa los siguientes parametros:
   - **Nombre de la tabla:** `clasificador-residuos`
   - **Clave de particion (Partition key):** `imagen_id` (Tipo: Cadena / String).
   - En **Configuracion de tabla**, selecciona **Personalizar configuracion** (Customize settings).
   - En **Modo de capacidad de lectura/escritura**, selecciona **Aprovisionado (Provisioned)** para aprovechar la capa **Always Free** de AWS (que incluye hasta 25 RCU y 25 WCU gratis de forma permanente):
     - **Capacidad de lectura:** Desactiva el escalado automatico (Auto scaling) y fija **5 unidades (RCU)**.
     - **Capacidad de escritura:** Desactiva el escalado automatico (Auto scaling) y fija **5 unidades (WCU)**.
4. Haz clic en **Crear tabla**.
5. Cuando la tabla este en estado *Activo*:
   - Entra a la tabla y selecciona la pestaña **Configuracion adicional** (Additional settings).
   - Localiza la seccion **Periodo de vida util (TTL)** y haz clic en **Administrar TTL**.
   - Marca la casilla **Habilitar TTL**.
   - **Nombre del atributo TTL:** `ttl`
   - Haz clic en **Guardar cambios**.

---

## Paso 2: Crear el Bucket S3 para Fotos Temporales

1. Ve al servicio **Amazon S3**.
2. Haz clic en **Crear bucket** (Create bucket).
3. Configura:
   - **Nombre del bucket:** Asigna un nombre unico global, por ejemplo: `clasificador-fotos-[tu-nombre-o-id]`
   - **Region de AWS:** Elige tu region de trabajo (por ejemplo `us-east-1`).
   - Mantén marcado **Bloquear todo el acceso publico** (Block all public access). Este bucket debe permanecer privado.
4. Haz clic en **Crear bucket**.
5. Entra al bucket recien creado y selecciona la pestaña **Permisos** (Permissions):
   - Baja hasta la seccion **Uso compartido de recursos entre origenes (CORS)** y haz clic en **Editar**.
   - Pega el siguiente JSON:

```json
[
  {
    "AllowedHeaders": [
      "*"
    ],
    "AllowedMethods": [
      "PUT",
      "GET",
      "HEAD"
    ],
    "AllowedOrigins": [
      "*"
    ],
    "ExposeHeaders": []
  }
]
```
   - Haz clic en **Guardar cambios**.

6. *(Opcional)* En la pestaña **Administracion** (Management), crea una regla de ciclo de vida:
   - Nombre de la regla: `EliminarFotosTemporales`
   - Prefijo: `uploads/`
   - Accion: Expirar versiones actuales de objetos tras **1 dia**.

---

## Paso 3: Crear el Rol de IAM para Lambda

1. Ve al servicio **IAM**.
2. En el menu lateral selecciona **Roles** y haz clic en **Crear rol** (Create role).
3. Selecciona:
   - **Tipo de entidad de confianza:** Servicio de AWS (AWS service).
   - **Caso de uso:** Lambda.
   - Haz clic en **Siguiente**.
4. En politicas de permisos, busca y selecciona:
   - `AWSLambdaBasicExecutionRole`
   - `AmazonRekognitionReadOnlyAccess`
5. Haz clic en **Siguiente**.
6. **Nombre del rol:** `ClasificadorResiduosLambdaRole`.
7. Haz clic en **Crear rol**.
8. Abre el rol `ClasificadorResiduosLambdaRole` recien creado:
   - En la pestaña **Permisos**, haz clic en **Agregar permisos** > **Crear directiva insertada** (Create inline policy).
   - Selecciona la pestaña **JSON** y reemplaza el contenido por:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3BucketAccess",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject"
      ],
      "Resource": "arn:aws:s3:::NOMBRE-DE-TU-BUCKET-FOTOS/*"
    },
    {
      "Sid": "DynamoDBTableAccess",
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:GetItem"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/clasificador-residuos"
    }
  ]
}
```
   *(Sustituye `NOMBRE-DE-TU-BUCKET-FOTOS` por el nombre real de tu bucket creado en el Paso 2).*
   - Haz clic en **Siguiente**, nombra la directiva `ClasificadorAppPermissions` y haz clic en **Crear directiva**.

---

## Paso 4: Crear las 3 Funciones Lambda

Cada funcion tiene su propio archivo independiente dentro de la carpeta `lambdas/` y define `lambda_handler` como punto de entrada, por lo que puedes pegar su contenido directamente sobre el archivo `lambda_function.py` que crea la consola por defecto sin cambiar el controlador (Handler).

### 4.1. Lambda 1: `clasificador-presign`
1. Ve al servicio **AWS Lambda** y haz clic en **Crear una funcion**.
2. Parámetros:
   - **Nombre de la funcion:** `clasificador-presign`
   - **Tiempo de ejecucion:** Python 3.12
   - **Arquitectura:** x86_64
   - **Rol de ejecucion:** Utilizar un rol existente -> `ClasificadorResiduosLambdaRole`
3. Haz clic en **Crear una funcion**.
4. En la pestaña **Codigo**:
   - Reemplaza el contenido del archivo `lambda_function.py` con el codigo completo de `lambdas/presign.py`.
   - El **Controlador (Handler)** puede quedar en su valor predeterminado (`lambda_function.lambda_handler`).
   - Haz clic en el boton **Deploy** en el editor de codigo.
5. En la pestaña **Configuracion**:
   - En **Variables de entorno**, agrega:
     - `BUCKET`: Nombre de tu bucket de fotos.
   - En **Configuracion general**, edita el **Tiempo de espera (Timeout)** a **15 segundos**.

### 4.2. Lambda 2: `clasificador-analizar`
1. Crea una nueva funcion Lambda:
   - **Nombre de la funcion:** `clasificador-analizar`
   - **Tiempo de ejecucion:** Python 3.12
   - **Rol de ejecucion:** `ClasificadorResiduosLambdaRole`
2. En la pestaña **Codigo**:
   - Reemplaza el contenido de `lambda_function.py` con el codigo completo de `lambdas/analizar.py`.
   - Haz clic en **Deploy**.
3. En la pestaña **Configuracion**:
   - **Variables de entorno**:
     - `BUCKET`: Nombre de tu bucket de fotos.
     - `TABLE`: `clasificador-residuos`
   - **Configuracion general**:
     - **Tiempo de espera (Timeout):** **30 segundos**.
     - **Memoria:** 256 MB.

### 4.3. Lambda 3: `clasificador-resultado`
1. Crea una nueva funcion Lambda:
   - **Nombre de la funcion:** `clasificador-resultado`
   - **Tiempo de ejecucion:** Python 3.12
   - **Rol de ejecucion:** `ClasificadorResiduosLambdaRole`
2. En la pestaña **Codigo**:
   - Reemplaza el contenido de `lambda_function.py` con el codigo completo de `lambdas/resultado.py`.
   - Haz clic en **Deploy**.
3. En la pestaña **Configuracion**:
   - **Variables de entorno**:
     - `TABLE`: `clasificador-residuos`
   - **Configuracion general**:
     - **Tiempo de espera (Timeout):** **15 segundos**.

---

## Paso 5: Configurar Disparador (Trigger) S3

1. Abre la funcion Lambda `clasificador-analizar`.
2. En la seccion **Informacion general de la funcion**, haz clic en **Agregar desencadenador** (Add trigger).
3. Selecciona **S3**:
   - **Bucket:** Selecciona tu bucket de fotos temporales.
   - **Tipo de evento:** `Todos los eventos de creacion de objetos` (`s3:ObjectCreated:*`).
   - **Prefijo:** `uploads/`
   - Marca la casilla de verificacion sobre invocaciones recursivas.
4. Haz clic en **Agregar**.

---

## Paso 6: Crear y Configurar API Gateway (REST API)

1. Ve al servicio **Amazon API Gateway**.
2. Haz clic en **Crear API** y selecciona **API REST** (haz clic en **Compilar**).
3. Configuracion:
   - **Protocolo:** REST
   - **Crear nueva API:** Nueva API
   - **Nombre de la API:** `clasificador-api`
   - **Tipo de punto de enlace:** Regional
4. Haz clic en **Crear API**.

### 6.1. Endpoint `/subir` (POST)
1. Con la raiz `/` seleccionada, haz clic en **Crear recurso**:
   - **Nombre del recurso:** `subir`
   - Haz clic en **Crear recurso**.
2. Con `/subir` seleccionado, haz clic en **Crear metodo**:
   - **Tipo de metodo:** `POST`
   - **Tipo de integracion:** Funcion Lambda
   - Marca **Integracion de proxy de Lambda**.
   - **Funcion Lambda:** `clasificador-presign`
   - Haz clic en **Crear metodo**.
3. Con `/subir` seleccionado, haz clic en **Habilitar CORS**:
   - Asegurate de marcar `POST` y `OPTIONS`.
   - Haz clic en **Guardar**.

### 6.2. Endpoint `/resultado` (GET)
1. Selecciona la raiz `/` y haz clic en **Crear recurso**:
   - **Nombre del recurso:** `resultado`
   - Haz clic en **Crear recurso**.
2. Con `/resultado` seleccionado, haz clic en **Crear metodo**:
   - **Tipo de metodo:** `GET`
   - **Tipo de integracion:** Funcion Lambda
   - Marca **Integracion de proxy de Lambda**.
   - **Funcion Lambda:** `clasificador-resultado`
   - Haz clic en **Crear metodo**.
3. Con `/resultado` seleccionado, haz clic en **Habilitar CORS**:
   - Asegurate de marcar `GET` y `OPTIONS`.
   - Haz clic en **Guardar**.

### 6.3. Despliegue de la API
1. Haz clic en el boton **Implementar API** (Deploy API):
   - **Etapa (Stage):** `*Nueva etapa*`
   - **Nombre de la etapa:** `prod`
2. Haz clic en **Implementar**.
3. Copia la **URL de invocacion** generada. Ejemplo:
   `https://abc123xyz.execute-api.us-east-1.amazonaws.com/prod`

---

## Paso 7: Alojar el Frontend en Amazon S3

1. Ve a **Amazon S3** y haz clic en **Crear bucket**.
2. Parametros:
   - **Nombre del bucket:** Nombre unico, ej: `clasificador-frontend-web-[tu-id]`
   - En **Bloquear todo el acceso publico**: **Desmarca** la casilla.
   - Marca la casilla de confirmacion reconociendo que los objetos seran publicos.
3. Haz clic en **Crear bucket**.
4. Entra al bucket recien creado:
   - Ve a la pestaña **Propiedades** (Properties).
   - Desplázate al final hasta **Alojamiento de sitios web estaticos** y haz clic en **Editar**.
   - Selecciona **Habilitar**.
   - **Documento de indice:** `index.html`
   - Haz clic en **Guardar cambios**.
5. Ve a la pestaña **Permisos** (Permissions):
   - En **Politica de bucket**, haz clic en **Editar**.
   - Pega la siguiente directiva reemplazando `NOMBRE-DE-TU-BUCKET-FRONTEND`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::NOMBRE-DE-TU-BUCKET-FRONTEND/*"
    }
  ]
}
```
   - Haz clic en **Guardar cambios**.
6. Ve a la pestaña **Objetos** (Objects):
   - Haz clic en **Cargar** (Upload).
   - Sube el archivo `frontend/index.html`.

---

## Paso 8: Verificacion y Uso

1. En el bucket del frontend, ve a **Propiedades** > **Alojamiento de sitios web estaticos**.
2. Abre la URL publica del bucket (ejemplo: `http://clasificador-frontend-web-[tu-id].s3-website.us-east-1.amazonaws.com`).
3. En el campo superior de la interfaz, introduce la **URL de invocacion de API Gateway** (obtenida en el Paso 6.3).
4. Carga o arrastra una fotografia de un residuo (manzana, botella, envoltura, etc.) y presiona **Clasificar residuo**.
5. Comprueba que el bote de basura y el desglose de etiquetas se muestren correctamente.
