# Guia de Despliegue con Amazon CloudFront

Esta guia describe el proceso para desplegar el Clasificador Inteligente de Residuos utilizando **Amazon CloudFront** como Red de Distribucion de Contenido (CDN) segura frente a un bucket privado de Amazon S3, empleando **Origin Access Control (OAC)** y conexiones cifradas bajo HTTPS.

---

## Ventajas de Usar CloudFront

- **Seguridad mejorada:** El bucket S3 que contiene el frontend permanece 100% privado, con "Bloquear todo el acceso publico" activado.
- **HTTPS predeterminado:** Proporciona cifrado SSL/TLS de extremo a extremo sin costo adicional con el certificado `*.cloudfront.net`.
- **Rendimiento y latencia:** El contenido estatico se almacena en cache en las ubicaciones de borde (Edge Locations) de AWS alrededor del mundo.
- **Opcion de dominio unificado:** Permite enrutar peticiones de API Gateway bajo el mismo dominio de CloudFront, evitando problemas de CORS en navegadores.

---

## Arquitectura de la Solucion

- **Frontend:** Amazon S3 (bucket estrictamente privado) servido a traves de Amazon CloudFront con OAC.
- **Almacenamiento de Fotos:** Amazon S3 (bucket temporal privado con CORS para subidas prefirmadas).
- **Base de Datos:** Amazon DynamoDB (`clasificador-residuos`).
- **Seguridad Backend:** Rol de AWS IAM para las funciones Lambda.
- **Compute:** 3 Funciones AWS Lambda independientes (Python 3.12 en `lambdas/`).
- **Disparador:** Notificacion de eventos S3 sobre el prefijo `uploads/`.
- **API:** Amazon API Gateway (REST API regional con endpoints `/subir` y `/resultado`).

---

## Fase 1: Despliegue del Backend

El backend se configura siguiendo los mismos pasos descritos en la guia de consola:

1. **DynamoDB:**
   - Crear la tabla `clasificador-residuos` con partition key `imagen_id` (String) en modo **Aprovisionado (Provisioned)** con **5 RCU y 5 WCU** (sin auto-scaling) para entrar en el nivel **Always Free** de AWS.
   - Habilitar TTL con el atributo `ttl`.
2. **Bucket S3 de Fotos Temporales:**
   - Crear bucket privado (ej: `clasificador-fotos-[id]`).
   - Configurar la regla CORS para metodos `PUT`, `GET`, `HEAD`.
3. **Rol IAM:**
   - Crear el rol `ClasificadorResiduosLambdaRole` para Lambda con `AWSLambdaBasicExecutionRole`, `AmazonRekognitionReadOnlyAccess` y politica inline para S3 y DynamoDB.
4. **Funciones Lambda (carpeta `lambdas/`):**
   - `clasificador-presign` (Codigo: `lambdas/presign.py`, Timeout: 15s, Variable `BUCKET`).
   - `clasificador-analizar` (Codigo: `lambdas/analizar.py`, Timeout: 30s, Memoria: 256MB, Variables `BUCKET` y `TABLE`).
   - `clasificador-resultado` (Codigo: `lambdas/resultado.py`, Timeout: 15s, Variable `TABLE`).
   - En cada funcion, pegar el codigo en `lambda_function.py` dejando el Handler por defecto (`lambda_function.lambda_handler`).
5. **Trigger S3:**
   - Enlazar el bucket de fotos a `clasificador-analizar` para eventos `s3:ObjectCreated:*` con prefijo `uploads/`.
6. **API Gateway:**
   - Crear REST API `clasificador-api` con recursos `/subir` (POST) y `/resultado` (GET) apuntando a sus respectivas Lambdas mediante integracion proxy.
   - Habilitar CORS en ambos recursos.
   - Desplegar la API en la etapa `prod` y copiar la URL de invocacion:
     `https://[api-id].execute-api.[region].amazonaws.com/prod`

---

## Fase 2: Crear el Bucket S3 Privado para el Frontend

1. Ve a **Amazon S3** y haz clic en **Crear bucket**.
2. Parametros:
   - **Nombre del bucket:** Por ejemplo, `clasificador-frontend-cf-[tu-id]`.
   - **Region:** La misma region de tu proyecto.
   - **Bloquear todo el acceso publico (Block all public access):** Mantén la casilla **marcada** (activo). No debe ser publico.
3. Haz clic en **Crear bucket**.
4. Entra al bucket recien creado y ve a la pestaña **Objetos**:
   - Haz clic en **Cargar** (Upload).
   - Sube el archivo `frontend/index.html`.
   *(Nota: No es necesario habilitar "Alojamiento de sitios web estaticos" en las propiedades del bucket).*

---

## Fase 3: Crear la Distribucion de CloudFront

1. Ve al servicio **CloudFront** en la consola de AWS.
2. Haz clic en **Crear distribucion** (Create distribution).
3. En la seccion **Origen** (Origin):
   - **Dominio de origen (Origin domain):** Selecciona el bucket S3 del frontend creado en la Fase 2 (aparecera en la lista desplegable con formato `clasificador-frontend-cf-[id].s3.amazonaws.com`).
   - **Acceso al origen (Origin access):** Selecciona **Configuracion de control de acceso de origen (recomendado)** / *Origin access control settings (recommended)*.
   - Haz clic en **Crear nueva configuracion de control de acceso** (Create control setting).
     - Deja el nombre sugerido y la firma predeterminada (Sign requests).
     - Haz clic en **Crear**.
4. En la seccion **Configuracion de comportamiento predeterminado** (Default cache behavior):
   - **Politica de protocolo del visor (Viewer protocol policy):** Selecciona **Redirigir HTTP a HTTPS** (Redirect HTTP to HTTPS).
   - **Metodos HTTP permitidos (Allowed HTTP methods):** Selecciona `GET, HEAD`.
   - **Politica de cache (Cache policy):** Selecciona `CachingOptimized`.
5. En la seccion **Configuracion** (Settings):
   - **Clase de precio (Price class):** Puedes seleccionar *Utilizar solo Norteamerica y Europa* (Use only North America and Europe) para optimizar costos, o *Utilizar todas las ubicaciones de borde*.
   - **Objeto raiz predeterminado (Default root object):** Escribe exactamente `index.html`.
6. Haz clic en **Crear distribucion** (Create distribution).

---

## Fase 4: Aplicar la Politica de Acceso OAC en S3

Al crearse la distribucion, CloudFront mostrara una alerta en amarillo indicando que debes actualizar la politica de tu bucket S3.

1. Haz clic en el boton **Copiar politica** (Copy policy) que aparece en el banner de CloudFront.
2. Si cerraste el banner, la estructura de la politica es la siguiente:

```json
{
  "Version": "2012-10-17",
  "Statement": {
    "Sid": "AllowCloudFrontServicePrincipalReadOnly",
    "Effect": "Allow",
    "Principal": {
      "Service": "cloudfront.amazonaws.com"
    },
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::clasificador-frontend-cf-[tu-id]/*",
    "Condition": {
      "StringEquals": {
        "AWS:SourceArn": "arn:aws:cloudfront::[NUMERO-DE-CUENTA]:distribution/[DISTRIBUTION-ID]"
      }
    }
  }
}
```

3. Ve al bucket S3 del frontend (`clasificador-frontend-cf-[tu-id]`):
   - Entra en la pestaña **Permisos** (Permissions).
   - En **Politica de bucket** (Bucket policy), haz clic en **Editar**.
   - Pega la politica copiada y haz clic en **Guardar cambios**.

---

## Fase 5 (Opcional): Unificar API Gateway bajo el Dominio de CloudFront

Para que el frontend y la API compartan el mismo dominio HTTPS (eliminando la necesidad de CORS en navegadores):

1. En tu distribucion de CloudFront, ve a la pestaña **Origenes** (Origins) y haz clic en **Crear origen**:
   - **Dominio de origen:** Pega el host de API Gateway (ejemplo: `[api-id].execute-api.[region].amazonaws.com`).
   - **Protocolo:** Solo HTTPS (HTTPS only).
   - **Ruta de origen (Origin path):** `/prod`
   - Haz clic en **Crear origen**.
2. Ve a la pestaña **Comportamientos** (Behaviors) y haz clic en **Crear comportamiento**:
   - **Patron de ruta (Path pattern):** `/subir`
   - **Origen:** Selecciona el origen de API Gateway creado en el paso anterior.
   - **Viewer protocol policy:** Redirect HTTP to HTTPS.
   - **Metodos HTTP permitidos:** `GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE`.
   - **Cache policy:** `CachingDisabled`.
   - **Origin request policy:** `AllViewerExceptHostHeader`.
   - Haz clic en **Crear comportamiento**.
3. Repite el paso para el patron de ruta `/resultado`.

Si aplicas esta configuracion, la URL base de la API en el frontend sera simplemente la misma direccion de CloudFront (o relativa).

---

## Fase 6: Verificacion y Pruebas

1. En la consola de CloudFront, ve a la seccion **General** de tu distribucion.
2. Espera a que el estado pase de *Desplegando* (Deploying) a *Habilitado* (Enabled).
3. Copia el **Nombre de dominio de distribucion** (Distribution domain name). Ejemplo:
   `https://d111111abcdef8.cloudfront.net`
4. Abre la URL en tu navegador web. Se cargara el clasificador de residuos mediante conexion segura HTTPS.
5. Pega la URL de tu API Gateway en el campo de configuracion superior (a menos que hayas implementado la Fase 5 opcional).
6. Sube una foto de prueba para clasificar un residuo y valida la respuesta del clasificador.
