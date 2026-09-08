"""Explicit deployment bootstrap; the API never creates buckets implicitly."""

import argparse
import time

from botocore.exceptions import BotoCoreError, ClientError

from voice_ingest.media.storage import S3Storage
from voice_ingest.runtime.settings import Settings


def initialize(storage: S3Storage, cleanup: str):
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
    if cleanup == "s3_lifecycle":
        try:
            rules = storage.internal.get_bucket_lifecycle_configuration(Bucket=storage.bucket)[
                "Rules"
            ]
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "NoSuchLifecycleConfiguration":
                raise
            rules = []
        rules = [rule for rule in rules if rule["ID"] != "abort-orphaned-uploads"]
        rules.append(
            {
                "ID": "abort-orphaned-uploads",
                "Status": "Enabled",
                "Filter": {"Prefix": "audio/"},
                "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
            }
        )
        storage.internal.put_bucket_lifecycle_configuration(
            Bucket=storage.bucket, LifecycleConfiguration={"Rules": rules}
        )
        print("Private bucket ready; S3 orphan multipart lifecycle configured")
    elif cleanup == "minio":
        # MinIO does not implement this lifecycle action; Compose configures its server scanner.
        print("Private bucket ready; orphan multipart cleanup is managed by MinIO server settings")
    else:
        raise ValueError("Select an explicit storage cleanup strategy")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cleanup", choices=["s3_lifecycle", "minio"], default="s3_lifecycle")
    args = parser.parse_args()
    try:
        initialize(S3Storage(Settings()), args.cleanup)
    except Exception:
        parser.exit(
            1, "Storage initialization failed; check connectivity, permissions and cleanup mode.\n"
        )
