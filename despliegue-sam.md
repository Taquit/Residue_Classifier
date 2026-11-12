# Guia de Despliegue con AWS SAM CLI (Recomendada)

Despliega **todo el proyecto con comandos**: backend (API Gateway, 3 Lambdas, S3, DynamoDB) y frontend publico en HTTPS (S3 privado + CloudFront con OAC). Es la forma mas rapida de replicarlo, por ejemplo para un taller.

## Que crea `template.yaml`

| Recurso | Funcion |
|---|---|
| `ClasificadorApi` | API Gateway REST (`POST /subir`, `GET /resultado`) con CORS |
| `PresignFunction`, `AnalizarFunction`, `ResultadoFunction` | Las 3 Lambdas (Python 3.12) |
| `ImagenesBucket` | Bucket de fotos (CORS para PUT, expiracion a 1 dia, trigger a `AnalizarFunction`) |
| `ResiduosTable` | DynamoDB provisionado 5 RCU / 5 WCU con TTL |
| `FrontendBucket` + `FrontendDistribution` | Bucket privado del frontend servido por CloudFront (HTTPS, necesario para usar la camara del celular). Tambien enruta `/api/*` hacia API Gateway mediante una CloudFront Function que quita el prefijo `/api` |

## Requisitos

- Cuenta de AWS con credenciales configuradas (`aws configure`) y permisos para crear los recursos anteriores.
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) y [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html).
- **Python 3.12 o Docker.** `sam build` necesita Python 3.12 en el PATH. Si tu sistema tiene otra version (por ejemplo 3.14), usa `sam build --use-container`, que compila dentro de un contenedor y requiere Docker o Podman.
- Rekognition debe estar disponible en la region elegida (por defecto `us-east-1`, definida en `samconfig.toml`).

## Despliegue

```bash
aws sts get-caller-identity          # confirma la cuenta correcta

sam build --use-container            # o `sam build` si tienes Python 3.12
sam deploy                           # usa samconfig.toml; confirma el changeset con "y"
```

CloudFront tarda unos 5-10 minutos en quedar listo la primera vez. Al terminar, `sam deploy` imprime los **Outputs**.

## Subir el frontend

El frontend no lo sube SAM; se copia al bucket con el nombre que aparece en el output `FrontendBucketName`:

```bash
aws s3 sync frontend/ s3://<FrontendBucketName>/
```

Tambien puedes obtener el nombre asi:

```bash
aws cloudformation describe-stacks --stack-name clasificador-residuos \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendBucketName'].OutputValue" --output text
```

## Compartir la aplicacion

El output `FrontendUrl` es el enlace listo para compartir (`https://<id>.cloudfront.net/`). No hay que configurar nada: CloudFront sirve el frontend en `/` y reenvia `/api/*` a API Gateway bajo el mismo dominio, asi que el frontend llama a la ruta relativa `/api` y la URL de API Gateway no aparece en la pagina ni en el enlace.

> La URL directa de API Gateway (output `ApiUrl`) sigue existiendo y es publica; simplemente no se muestra a los usuarios.

Prueba el enlace desde un celular antes de compartirlo: debe pedir permiso de camara y devolver un resultado tras subir una foto.

## Parametros

| Parametro | Default | Descripcion |
|---|---|---|
| `AllowedOrigin` | `*` | Origen permitido para CORS del bucket de fotos y de la URL directa de la API. El frontend usa el mismo dominio para la API, por lo que no se necesita CORS ahi. |

Para restringirlo al dominio de CloudFront tras el primer despliegue:

```bash
sam deploy --parameter-overrides AllowedOrigin=https://<id>.cloudfront.net
```

## Actualizar

- **Cambios en Lambdas o template:** `sam build --use-container && sam deploy`.
- **Cambios en el frontend:** `aws s3 sync frontend/ s3://<FrontendBucketName>/` y, si no ves el cambio, invalida la cache: `aws cloudfront create-invalidation --distribution-id <id> --paths "/*"`.

## Eliminar todo

Los buckets deben estar vacios o el borrado del stack falla:

```bash
aws s3 rm s3://<FrontendBucketName> --recursive
aws s3 rm s3://<BucketName> --recursive      # output BucketName (fotos)
sam delete --no-prompts
```

## Seguridad

La API es publica y no tiene autenticacion: cada foto genera una llamada a Rekognition. Es adecuado para demos o talleres de corta duracion; para uso prolongado agrega throttling (`MethodSettings`), una API key o restringe `AllowedOrigin`. Elimina el stack al terminar.

## Problemas comunes

| Sintoma | Causa / solucion |
|---|---|
| `Binary validation failed for python ... python3.12` | No hay Python 3.12 en el PATH. Usa `sam build --use-container`. |
| El enlace de CloudFront da 403 | Falta ejecutar `aws s3 sync frontend/ ...` o la distribucion aun se esta propagando. |
| El navegador no abre la camara | Debe usarse el enlace HTTPS de CloudFront, no un `index.html` local por HTTP. |
| `sam delete` falla | Algun bucket no esta vacio; vacialos primero. |
