from __future__ import unicode_literals
from backports import csv
from io import open
import os
import posixpath
from django.conf import settings
from django.core.files.storage import get_storage_class
from django.core.management.base import BaseCommand
from images.models import Image


class Command(BaseCommand):

    help = ("Check for Image objects in the database that reference"
            " nonexistent image filepaths")

    def handle(self, *args, **options):
        storage = get_storage_class()()

        images_relative_dir = posixpath.split(settings.IMAGE_FILE_PATTERN)[0]

        self.stdout.write(
            "Reading the image files directory: {dir}. This could take"
            " a while...".format(dir=images_relative_dir))
        dirnames, filenames = storage.listdir(images_relative_dir)
        filenames = set(filenames)

        self.stdout.write(
            "Finished reading the image files directory:"
            " {n} files found.".format(n=len(filenames)))
        self.stdout.write(
            "Checking database entries for missing image files...")

        images = Image.objects.all()
        total_images = images.count()
        image_count = 0
        missing_count = 0
        csv_filepath = os.path.join(
            settings.SITE_DIR, 'tmp', 'missing_images.csv')

        with open(csv_filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Source name", "Source id", "Image name",
                "Image id", "Image filename"])

            for img in images:
                filepath = img.original_file.name
                dir, filename = posixpath.split(filepath)
                if dir != images_relative_dir:
                    # Directory mismatch, so there's no way the file
                    # is found. Force the missing-file case.
                    filename = None

                if filename not in filenames:
                    self.stdout.write(
                        "{source_name} ({source_pk}) / {meta_name} ({img_pk})"
                        " is missing - {file_name}".format(
                            source_name=img.source.name,
                            source_pk=img.source.pk,
                            meta_name=img.metadata.name, img_pk=img.pk,
                            file_name=filename))
                    writer.writerow([
                        img.source.name, img.source.pk, img.metadata.name,
                        img.pk, filename])
                    missing_count += 1

                image_count += 1
                if image_count % 1000 == 0:
                    self.stdout.write("({n}/{t} Image objects checked)".format(
                        n=image_count, t=total_images))

            if missing_count == 0:
                self.stdout.write(self.style.SUCCESS(
                    "There were {c} missing files out of {t}.".format(
                        c=missing_count, t=image_count)))
            else:
                self.stdout.write(self.style.ERROR(
                    "There were {c} missing files out of {t}. A CSV of the"
                    " missing files was created at: {path}".format(
                        c=missing_count, t=image_count, path=csv_filepath)))
