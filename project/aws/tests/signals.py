from django.core.signals import setting_changed
from django.dispatch import receiver


@receiver(setting_changed)
def aws_location_changed(*, setting, **kwargs):
    """
    Update S3 storage location attributes when AWS_LOCATION is changed.
    This assumes that all S3 storages specified in STORAGES are using
    AWS_LOCATION and not their own location kwarg.

    Unlike django.test.signals.storages_changed(), this doesn't have to
    re-instantiate any storages, which makes a substantial time difference
    with S3 storage.
    """
    from django.core.files.storage import storages
    from storages.backends.s3 import S3Storage

    if setting == 'AWS_LOCATION':
        new_location = kwargs['value']

        for alias, storage in storages._storages.items():
            if isinstance(storage, S3Storage):
                storage.location = new_location
