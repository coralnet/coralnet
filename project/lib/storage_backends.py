from abc import ABCMeta
from contextlib import contextmanager
from importlib import import_module
import os
from pathlib import Path
import shutil
import tempfile

from django.conf import settings
from django.core.files.storage import default_storage, FileSystemStorage
from django.test import override_settings
from spacer.data_classes import DataLocation

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


class StorageManagerLocal(StorageManager):

    def copy_dir(self, src, dst):
        shutil.copytree(src, dst, dirs_exist_ok=True)

    @contextmanager
    def override_default_storage_dir(self, storage_dir):
        # For local storage, we only have to update where the media's stored,
        # not where it's served.
        media_root = default_storage.path_join(storage_dir, 'media')
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


def get_storage_manager():
    """
    Returns an instance of the StorageManager that's applicable to the default
    storage backend.
    """
    backend_class_path = settings.STORAGES['default']['BACKEND']
    if backend_class_path not in settings.STORAGE_MANAGERS:
        raise FileStorageUsageError(
            f"No manager for the storage backend {backend_class_path}.")

    manager_class_path = settings.STORAGE_MANAGERS[backend_class_path]
    module_path, class_name = manager_class_path.rsplit('.', 1)
    module = import_module(module_path)
    manager_class = getattr(module, class_name)

    if not (
        isinstance(manager_class, type)
        and issubclass(manager_class, StorageManager)
    ):
        raise TypeError(
            f"{manager_class_path} is not a StorageManager subclass."
        )

    manager = manager_class()
    return manager
