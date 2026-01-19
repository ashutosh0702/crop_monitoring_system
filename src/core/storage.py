"""
S3 Storage Service for file uploads and URL generation.
Supports local filesystem in development and S3 in production.
"""

import os
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime
import mimetypes

import boto3
from botocore.exceptions import ClientError

from src.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    """
    Unified storage service supporting both local filesystem and S3.
    
    In development: Files stored in ./data/ directory
    In production: Files uploaded to S3 bucket
    """
    
    def __init__(self):
        self.use_s3 = settings.use_s3
        
        if self.use_s3:
            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION,
            )
            self.bucket_name = settings.AWS_S3_BUCKET
            logger.info(f"📦 Storage: S3 bucket '{self.bucket_name}'")
        else:
            self.s3_client = None
            self.bucket_name = None
            self.local_base = Path("./data")
            self.local_base.mkdir(parents=True, exist_ok=True)
            logger.info(f"📦 Storage: Local filesystem '{self.local_base}'")
    
    def upload_file(
        self,
        file_path: Path,
        object_key: str,
        content_type: Optional[str] = None
    ) -> str:
        """
        Upload a file to storage and return its URL.
        
        Args:
            file_path: Local path to the file
            object_key: S3 object key / relative path
            content_type: MIME type (auto-detected if not provided)
            
        Returns:
            URL to access the file
        """
        if content_type is None:
            content_type, _ = mimetypes.guess_type(str(file_path))
            content_type = content_type or 'application/octet-stream'
        
        if self.use_s3:
            return self._upload_to_s3(file_path, object_key, content_type)
        else:
            return self._save_local(file_path, object_key)
    
    def upload_bytes(
        self,
        data: bytes,
        object_key: str,
        content_type: str = 'application/octet-stream'
    ) -> str:
        """
        Upload bytes directly to storage.
        
        Args:
            data: Raw bytes to upload
            object_key: S3 object key / relative path
            content_type: MIME type
            
        Returns:
            URL to access the file
        """
        if self.use_s3:
            return self._upload_bytes_to_s3(data, object_key, content_type)
        else:
            return self._save_bytes_local(data, object_key)
    
    def _upload_to_s3(
        self,
        file_path: Path,
        object_key: str,
        content_type: str
    ) -> str:
        """Upload file to S3."""
        try:
            self.s3_client.upload_file(
                str(file_path),
                self.bucket_name,
                object_key,
                ExtraArgs={'ContentType': content_type}
            )
            url = f"https://{self.bucket_name}.s3.{settings.AWS_REGION}.amazonaws.com/{object_key}"
            logger.info(f"Uploaded to S3: {object_key}")
            return url
        except ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            raise
    
    def _upload_bytes_to_s3(
        self,
        data: bytes,
        object_key: str,
        content_type: str
    ) -> str:
        """Upload bytes to S3."""
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=object_key,
                Body=data,
                ContentType=content_type
            )
            url = f"https://{self.bucket_name}.s3.{settings.AWS_REGION}.amazonaws.com/{object_key}"
            logger.info(f"Uploaded bytes to S3: {object_key}")
            return url
        except ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            raise
    
    def _save_local(self, file_path: Path, object_key: str) -> str:
        """Save file to local filesystem."""
        dest_path = self.local_base / object_key
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Copy file if source is different from destination
        if str(file_path) != str(dest_path):
            import shutil
            shutil.copy2(file_path, dest_path)
        
        logger.info(f"Saved locally: {dest_path}")
        return str(dest_path.absolute())
    
    def _save_bytes_local(self, data: bytes, object_key: str) -> str:
        """Save bytes to local filesystem."""
        dest_path = self.local_base / object_key
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        dest_path.write_bytes(data)
        logger.info(f"Saved bytes locally: {dest_path}")
        return str(dest_path.absolute())
    
    def get_presigned_url(
        self,
        object_key: str,
        expiration: int = 3600
    ) -> Optional[str]:
        """
        Generate a presigned URL for temporary access to a file.
        
        Args:
            object_key: S3 object key
            expiration: URL expiration time in seconds
            
        Returns:
            Presigned URL or None if local storage
        """
        if not self.use_s3:
            # For local, just return the file path
            return str(self.local_base / object_key)
        
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': object_key},
                ExpiresIn=expiration
            )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            return None
    
    def delete_file(self, object_key: str) -> bool:
        """Delete a file from storage."""
        if self.use_s3:
            try:
                self.s3_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=object_key
                )
                return True
            except ClientError as e:
                logger.error(f"S3 delete failed: {e}")
                return False
        else:
            file_path = self.local_base / object_key
            if file_path.exists():
                file_path.unlink()
                return True
            return False


# Singleton instance
_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    """Get or create storage service singleton."""
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
