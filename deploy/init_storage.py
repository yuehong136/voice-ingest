"""Explicit deployment bootstrap; the API never creates buckets implicitly."""

import time

from botocore.exceptions import BotoCoreError, ClientError

from voice_ingest.media.storage import S3Storage
from voice_ingest.runtime.settings import Settings

settings = Settings()
storage = S3Storage(settings)
for attempt in range(30):
    try:
        storage.internal.head_bucket(Bucket=storage.bucket)
        break
    except ClientError as exc:
        if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
            storage.internal.create_bucket(Bucket=storage.bucket)
            break
        raise
    except BotoCoreError:
        if attempt == 29:
            raise RuntimeError("S3 did not become ready") from None
        time.sleep(2)
storage.internal.put_bucket_lifecycle_configuration(
    Bucket=storage.bucket,
    LifecycleConfiguration={
        "Rules": [
            {
                "ID": "abort-orphaned-uploads",
                "Status": "Enabled",
                "Filter": {"Prefix": "audio/"},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
            }
        ]
    },
)
print("Private bucket ready; orphan multipart cleanup configured")
