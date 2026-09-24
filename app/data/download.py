import os

import boto3
from dotenv import load_dotenv

from app.paths import RAW_PDFS_DIR

load_dotenv()

S3_BUCKET_NAME = "anyoneai-datasets"
S3_PREFIX = "queplan_insurance/"

AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")

LOCAL_OUTPUT_DIR = RAW_PDFS_DIR


def download_queplan_pdfs():
    if not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
        raise RuntimeError(
            "Faltan credenciales AWS: configura AWS_ACCESS_KEY_ID y "
            "AWS_SECRET_ACCESS_KEY en el archivo .env"
        )

    LOCAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Iniciando sesión en AWS S3...")

    s3_client = boto3.client(
        "s3",
        aws_access_key_id=AWS_ACCESS_KEY_ID,
        aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
    )

    print(f"Listando objetos en s3://{S3_BUCKET_NAME}/{S3_PREFIX}...")

    paginator = s3_client.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=S3_BUCKET_NAME, Prefix=S3_PREFIX)

    downloaded_count = 0

    for page in pages:
        if "Contents" not in page:
            print("No se encontraron archivos en la ruta especificada.")
            return

        for obj in page["Contents"]:
            s3_key = obj["Key"]

            if s3_key.endswith("/"):
                continue

            file_name = os.path.basename(s3_key)
            local_file_path = LOCAL_OUTPUT_DIR / file_name

            print(f"Descargando: {file_name} -> {local_file_path}")

            s3_client.download_file(
                Bucket=S3_BUCKET_NAME,
                Key=s3_key,
                Filename=str(local_file_path),
            )
            downloaded_count += 1

    print(
        f"\n¡Proceso completado! Se descargaron {downloaded_count} archivos en "
        f"'{LOCAL_OUTPUT_DIR.resolve()}'."
    )


if __name__ == "__main__":
    download_queplan_pdfs()