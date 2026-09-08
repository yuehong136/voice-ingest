import runpy

bootstrap = runpy.run_path("deploy/init_storage.py")["initialize"]


async def test_s3_bootstrap_preserves_existing_lifecycle_rules(env):
    client, bucket = env.storage.internal, env.storage.bucket
    client.put_bucket_lifecycle_configuration(
        Bucket=bucket,
        LifecycleConfiguration={
            "Rules": [
                {
                    "ID": "existing",
                    "Status": "Enabled",
                    "Filter": {"Prefix": "other/"},
                    "Expiration": {"Days": 100},
                }
            ]
        },
    )
    bootstrap(env.storage, "s3_lifecycle")
    bootstrap(env.storage, "s3_lifecycle")
    rules = client.get_bucket_lifecycle_configuration(Bucket=bucket)["Rules"]
    assert {rule["ID"] for rule in rules} == {"existing", "abort-orphaned-uploads"}
    assert len(rules) == 2


async def test_minio_bootstrap_does_not_send_unsupported_lifecycle_action(env, monkeypatch):
    def unsupported(**kwargs):
        raise AssertionError("MinIO does not support AbortIncompleteMultipartUpload lifecycle")

    monkeypatch.setattr(env.storage.internal, "put_bucket_lifecycle_configuration", unsupported)
    bootstrap(env.storage, "minio")
