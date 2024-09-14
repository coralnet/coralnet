from abc import ABCMeta
from contextlib import contextmanager
import os
from pathlib import Path
import posixpath
import random
import shutil
import string
import tempfile

from spacer.messages import DataLocation

from django.conf import settings
from django.core.files.storage import DefaultStorage, FileSystemStorage
from django.test import override_settings
from storages.backends.s3 import S3Storage

from .exceptions import FileStorageUsageError


# Abstract class
class StorageManager(object, metaclass=ABCMeta):

    def copy_dir(self, src, dst):
        """
        Copy a directory recursively from `src` to `dst`. Both should be
        absolute paths / paths from bucket root.
        """
        raise NotImplementedError

    @contextmanager
    def override_default_storage_dir(self, storage_dir):
        """
        Context manager which establishes storage_dir (an absolute
        path / path from bucket root) as the default-storage root for the
        context's duration.
        """
        raise NotImplementedError

    def create_temp_dir(self):
        """
        Create a directory for temporary files, and return its absolute path /
        path from bucket root.
        """
        raise NotImplementedError

    def _empty_dir(self, dir_to_empty):
        """
        Empty the directory at the given path, without actually removing the
        directory itself.
        """
        raise NotImplementedError

    def empty_temp_dir(self, dir_to_empty):
        """
        Check that a directory is most likely a temporary directory, then
        empty it. This is a safety check to prevent data loss.
        """
        if not self.is_temp_dir(dir_to_empty):
            raise FileStorageUsageError(
                self.not_temp_dir_explanation
                + " So we're not sure if it's safe to"
                + " empty this directory or not.")

        self._empty_dir(dir_to_empty)

    not_temp_dir_explanation = \
        "The dir path doesn't contain a 'tmp' or 'temp' dir (case insensitive)."

    @staticmethod
    def is_temp_dir(dir_to_check):
        """Check whether a directory is most likely a temporary directory."""
        parts = [part.lower() for part in Path(dir_to_check).parts]
        # If there are other possible temporary-directory name patterns,
        # add them here.
        return 'tmp' in parts or 'temp' in parts

    def _remove_dir(self, dir_to_remove):
        """Remove the directory at the given path."""
        raise NotImplementedError

    def remove_temp_dir(self, dir_to_remove):
        """
        Check that a directory is most likely a temporary directory, then
        remove it. This is a safety check to prevent data loss.
        """
        if not self.is_temp_dir(dir_to_remove):
            raise FileStorageUsageError(
                self.not_temp_dir_explanation
                + " So we're not sure if it's safe to"
                + " remove this directory or not.")

        self._remove_dir(dir_to_remove)


class StorageManagerS3(StorageManager):

    def copy_dir(self, src, dst):
        s3_root_storage = get_s3_root_storage()

        # List directories and files in this directory.
        subdirs, filenames = s3_root_storage.listdir(src)
        for filename in filenames:
            # Copy the file from src to dst.
            f = s3_root_storage.open(s3_root_storage.path_join(src, filename))
            s3_root_storage.save(s3_root_storage.path_join(dst, filename), f)
        for subdir in subdirs:
            # Copy the subdir from src to dst using recursion.
            self.copy_dir(
                s3_root_storage.path_join(src, subdir),
                s3_root_storage.path_join(dst, subdir))

    @contextmanager
    def override_default_storage_dir(self, storage_dir):
        storage = DefaultStorage()

        # DefaultStorage() returns a storage which may have already been
        # previously instantiated, in which case AWS_LOCATION won't be
        # re-read.
        # So instead of overriding the AWS_LOCATION setting,
        # we directly assign the passed dir to the storage's `location`
        # attribute.
        old_location = storage.location
        storage.location = storage.path_join(
            storage_dir, settings.AWS_S3_MEDIA_SUBDIR)

        # If the storage's base_url attribute is set, then it's used; else,
        # MEDIA_URL is read. Not at instantiation time, but any time it's
        # relevant.
        # Also, it's good to keep MEDIA_URL synced up with the storage dir,
        # since MEDIA_URL is used unconditionally in places like
        # LiveServerThread.
        # So we favor overriding MEDIA_URL instead of base_url.
        media_url = 'https://{domain}/{storage_dir}/{subdir}/'.format(
            domain=settings.AWS_S3_DOMAIN,
            storage_dir=storage_dir.strip('/'),
            subdir=settings.AWS_S3_MEDIA_SUBDIR,
        )
        with override_settings(MEDIA_URL=media_url):
            yield

        storage.location = old_location

    def create_temp_dir(self):
        s3_root_storage = get_s3_root_storage()

        # Doubtful that S3 has any concept of temporary directories, since
        # directories are already kind of a nebulous concept in S3: they
        # can't be created manually, but they automatically get created as you
        # save new filepaths, and automatically get deleted when emptied.
        #
        # So, we'll just create any old directory and attempt to clean it up
        # later. We just have to identify a free directory name to create files
        # in.
        #
        # get_available_name() already adds a random suffix as necessary
        # (like `_123abCD`) to avoid clashing with an existing name.
        # However, since S3 directories don't 'exist' until they contain files,
        # clashing can easily happen if we start off trying to create 2 temp
        # directories in a row (both will be be the non-suffixed name).
        # So, we just add our own random suffix to begin with.
        suffix = ''.join([
            random.choice(string.digits + string.ascii_letters)
            for _ in range(10)])
        dir_path = 'tmp/tmp_' + suffix
        return s3_root_storage.get_available_name(dir_path)

    def _empty_dir(self, dir_to_empty):
        # Emptying an S3 dir is equivalent to removing the dir. Empty dirs
        # shouldn't persist.
        self._remove_dir(dir_to_empty)

    def _remove_dir(self, dir_to_remove):
        # List directories and files in this directory.
        s3_root_storage = get_s3_root_storage()
        subdirs, filenames = s3_root_storage.listdir(dir_to_remove)

        for filename in filenames:
            # Remove the file.
            s3_root_storage.delete(
                s3_root_storage.path_join(dir_to_remove, filename))
        for subdir in subdirs:
            # Delete the subdir using recursion.
            self._remove_dir(
                s3_root_storage.path_join(dir_to_remove, subdir))


class StorageManagerLocal(StorageManager):

    def copy_dir(self, src, dst):
        shutil.copytree(src, dst, dirs_exist_ok=True)

    @contextmanager
    def override_default_storage_dir(self, storage_dir):
        storage = DefaultStorage()

        # For local storage, we only have to update where the media's stored,
        # not where it's served.
        media_root = storage.path_join(storage_dir, 'media')
        with override_settings(MEDIA_ROOT=media_root):
            yield

    def create_temp_dir(self):
        # We'll use an OS-designated temp dir.
        tmp_root = tempfile.mkdtemp()

        # Adding an extra subfolder just to be sure
        tmp_dir = os.path.join(tmp_root, 'temp')
        os.mkdir(tmp_dir)

        return tmp_dir

    def _empty_dir(self, dir_to_empty):
        # It seems that repeatedly removing and re-creating dirs can cause
        # errors such as 'no such file or directory', so we just remove the
        # files and keep the subdirs.
        # Use _remove_dir() to remove subdirs as well.
        for obj_path in Path(dir_to_empty).iterdir():
            if obj_path.is_file() or obj_path.is_symlink():
                obj_path.unlink()
            else:
                self._empty_dir(str(obj_path))

    def _remove_dir(self, dir_to_remove):
        shutil.rmtree(dir_to_remove)


class MediaStorageS3(S3Storage):
    """
    S3-bucket storage backend.
    Storage root defaults to the AWS_LOCATION directory.
    """
    def exists(self, name):
        # Check for existing file. This doesn't work on dirs.
        if super().exists(name):
            return True

        # Check for existing dir (Django's local storage class also returns
        # True on dirs). We do this by checking if listdir() returns any
        # dirs or files.
        dirs, files = self.listdir(name)
        return bool(dirs or files)

    def get_available_name(self, name, max_length=None):
        available_name = super().get_available_name(
            name, max_length=max_length)

        # Django's suffix-appending code uses os.path.join(), so if we're
        # running on Windows, the path will end up with backslash separators.
        # We want to change the backslashes to forward slashes, since S3 uses
        # forward slashes.
        # However, on the off chance that a dir/file name legitimately uses a
        # backslash, we'll only make this correction on Windows.
        if os.name == 'nt':
            available_name = available_name.replace('\\', '/')

        return available_name

    @staticmethod
    def path_join(*args):
        # For S3 paths, we join with forward slashes.
        return posixpath.join(*args)

    def spacer_data_loc(self, key) -> DataLocation:
        """ Returns a spacer DataLocation object """
        return DataLocation(storage_type='s3',
                            key=self._normalize_name(key),
                            bucket_name=self.bucket_name)


class MediaStorageLocal(FileSystemStorage):
    """
    Local-filesystem storage backend.
    Storage root defaults to MEDIA_ROOT.
    """
    @staticmethod
    def path_join(*args):
        # For local storage, we join paths depending on the OS rules.
        return os.path.join(*args)

    def spacer_data_loc(self, key) -> DataLocation:
        """ Returns a spacer DataLocation object. """
        return DataLocation(storage_type='filesystem',
                            key=self.path(key))
 

def get_s3_root_storage():
    """
    Returns an S3 storage backend which accepts operations throughout an
    entire bucket, rather than only within a settings-specified directory.
    """
    # S3 storage's __init__() accepts kwargs to override default attributes.
    # `location` is the path from the bucket root which will be used as the
    # storage root. We want to use bucket root as storage root, so we pass ''.
    return MediaStorageS3(location='')


def get_storage_manager():
    """
    Returns the StorageManager applicable to the default storage backend.
    """
    match settings.STORAGES['default']['BACKEND']:
        case 'lib.storage_backends.MediaStorageS3':
            return StorageManagerS3()
        case 'lib.storage_backends.MediaStorageLocal':
            return StorageManagerLocal()
        case _:
            raise FileStorageUsageError("Unrecognized storage backend.")
