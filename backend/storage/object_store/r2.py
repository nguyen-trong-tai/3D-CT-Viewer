"""
Cloudflare R2 object store implementation via the S3-compatible API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import ObjectStore


class R2ObjectStore(ObjectStore):
    """Upload and serve artifacts from Cloudflare R2."""

    def __init__(
        self,
        account_id: str,
        bucket: str,
        access_key_id: str,
        secret_access_key: str,
        public_base_url: str | None = None,
        region_name: str = "auto",
        max_pool_connections: int = 12,
        transfer_max_concurrency: int = 4,
        multipart_threshold_mb: int = 16,
        multipart_chunk_size_mb: int = 16,
    ):
        self.account_id = account_id
        self.bucket = bucket
        self.public_base_url = public_base_url.rstrip("/") if public_base_url else None
        self.endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        self.transfer_config = TransferConfig(
            multipart_threshold=max(1, multipart_threshold_mb) * 1024 * 1024,
            multipart_chunksize=max(1, multipart_chunk_size_mb) * 1024 * 1024,
            max_concurrency=max(1, transfer_max_concurrency),
            use_threads=True,
        )
        self.client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region_name,
            config=Config(
                max_pool_connections=max(1, max_pool_connections),
                retries={"max_attempts": 3, "mode": "standard"},
            ),
        )

    def verify_connection(self) -> None:
        """Validate that the configured bucket can be reached."""
        self.client.head_bucket(Bucket=self.bucket)

    def upload_file(self, local_path: Path, object_key: str, content_type: Optional[str] = None) -> str:
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        self.client.upload_file(
            str(local_path),
            self.bucket,
            object_key,
            ExtraArgs=extra_args or None,
            Config=self.transfer_config,
        )
        return object_key

    def upload_bytes(self, data: bytes, object_key: str, content_type: Optional[str] = None) -> str:
        extra_args = {}
        if content_type:
            extra_args["ContentType"] = content_type
        self.client.put_object(Bucket=self.bucket, Key=object_key, Body=data, **extra_args)
        return object_key

    def generate_download_url(self, object_key: str, expires_in_seconds: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=expires_in_seconds,
        )

    def generate_upload_url(self, object_key: str, expires_in_seconds: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=expires_in_seconds,
        )

    def download_bytes(self, object_key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=object_key)
        return response["Body"].read()

    def download_file(self, object_key: str, local_path: Path) -> Path:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(
            self.bucket,
            object_key,
            str(local_path),
            Config=self.transfer_config,
        )
        return local_path

    def object_exists(self, object_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=object_key)
            return True
        except ClientError:
            return False

    def delete_object(self, object_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=object_key)

    def delete_prefix(self, prefix: str) -> None:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            contents = page.get("Contents", [])
            if not contents:
                continue
            self.client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": [{"Key": item["Key"]} for item in contents]},
            )
