# These old functions have ideas that can still be useful for CoralNet's
# operations. They should be reworked and incorporated into management
# commands or jobs at some point.

import os
import re
import subprocess

from django.conf import settings

from images.models import Image
from sources.models import Source


def find_duplicate_imagenames():
    """
    This checks for duplicates among image names.
    """
    for source in Source.objects.filter():
        if not source.all_image_names_are_unique():
            print('==== Source {}[{}] ===='.format(source.name, source.id))
            dupes = 0
            for image in source.get_all_images().filter(metadata__name__in = source.get_nonunique_image_names()):
                #print image.id, image.metadata.name
                example = image.metadata.name
                dupes += 1
            total = source.get_all_images().count()
            print('{}/{} - Example: {}'.format(dupes, total, example))


def move_unused_image_files(dry_run=False):
    """
    # TODO: This code is for the alpha server.
    # Change it to work with the beta server when appropriate.
    # Also make this into a management command.
    """

    print("Checking the DB to see which filenames are in use...")
    filepaths_in_use_list = \
        Image.objects.all().values_list('original_file', flat=True)
    # We have a list of relative filepaths from the base media directory.
    # Get a set of filenames only (no directories).
    filenames_in_use = \
        {os.path.split(filepath)[-1] for filepath in filepaths_in_use_list}

    image_files_dir = os.path.join(settings.MEDIA_ROOT, 'data/original')
    unused_image_files_dir = '/unused_images'
    dot_number_regex = re.compile(r'\.\d')
    unused_image_count = 0
    checked_image_count = 0

    print("Checking the image files dir...")
    for filename in os.listdir(image_files_dir):
        checked_image_count += 1

        if filename in filenames_in_use:
            # Base image, in use
            continue

        # Example thumbnail filename: a1b2c3d4e5.jpg.150x150_q85.jpg
        # The base image filename comes before the first instance of
        # a dot followed by a number (.1 in this case).
        match = re.search(dot_number_regex, filename)
        if match:
            # Thumbnail image
            base_filename = filename[:(match.span()[0])]
            if base_filename in filenames_in_use:
                # In use
                continue

        # Filename is not in use; move it to the unused image files dir.
        unused_image_count += 1
        src_filepath = os.path.join(image_files_dir, filename)

        print("Moving {filename} ({unused} unused / {checked} checked)".format(
            filename=filename,
            unused=unused_image_count,
            checked=checked_image_count,
        ))
        if not dry_run:
            subprocess.call(
                ['sudo', 'mv', src_filepath, unused_image_files_dir])


