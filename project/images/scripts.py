"""
This file contains scripts that are not part of the main production server. But that reads/exports/manipulates things on a one-to-one basis.
"""

import os
import re
import subprocess

from django.conf import settings
import numpy as np

from images.models import Image
from sources.models import Source


def export_imgage_and_annotations(source_idlist, outdir):
    """
    This script exports all imges and annotations for the purpose of training
    a deep net.
    """

    for source_id in source_idlist:
        this_dir = os.path.join(outdir, 's{}'.format(source_id))
        os.mkdir(this_dir)
        os.mkdir(os.path.join(this_dir, 'imgs'))
        imdict = []
        source = Source.objects.get(id = source_id)
        for im in source.get_all_images:

            # Special check for MLC. Do not want the imgs from 2008!!!!
            if source_id == 16 and im.metadata.photo_date.year == 2008:
                continue
            if not im.status.annotatedByHuman:
                continue
            
            annlist = []
            for a in im.annotation_set.filter():
                annlist.append((a.label.name, a.point.row, a.point.column))
            imdict[im.metadata.name] = (annlist, im.height_cm())
            copyfile(os.path.join('/cnhome/media', str(i.original_file)), os.path.join(this_dir, 'imgs', im.metadata.name))
        pickle.dump(imdict, os.path.join(this_dir, 'imdict.p'))



def get_source_stats():
    """
    This script organizes some key stats of all the source, and puts it in a nice list.
    """
    nlabels = Label.objects.order_by('-id')[0].id #highest label id on the site
    labelname = {}
    labelfunc = {}
    funcname = {}
    for label in Label.objects.filter():
        labelname[label.id] = label.name
        labelfunc[label.id] = label.group_id
    for fg in LabelGroup.objects.filter():
        funcname[fg.id] = fg.name
    ss = []
    for s in Source.objects.filter():
        annlist = [a.label_id for a in s.annotation_set.confirmed()]
        if not annlist:
            continue
        print(s.name)
        sp = {}
        sp['name'] = s.name
        sp['lat'] = s.latitude
        sp['long'] = s.longitude
        sp['id'] = s.id
        sp['labelids'] = [l.id for l in s.labelset.get_globals()]
        sp['nlabels'] = s.labelset.get_labels().count()
        sp['nimgs'] = s.get_all_images().filter(status__annotatedByHuman=True).count()
        sp['nanns'] = len(annlist)
        sp['anncount'] = np.bincount(annlist, minlength = nlabels)
        ss.append(sp)
    return ss, labelname, labelfunc, funcname





def export_images(source_id, outDir, original_file_name = True):
    """
    This script exports all images from a source.
    """
    mysource = Source.objects.filter(id = source_id)
    images = Image.objects.filter(source = mysource[0])
    for i in images:
        m = i.metadata
        if original_file_name:
            fname = m.name
        else:
            fname = str(m.value1) + '_' + str(m.value2) + '_' + \
            str(m.value3) + '_' + str(m.value4) + '_' + str(m.value5) + \
            '_' + m.photo_date.isoformat() + '.jpg'
        copyfile(os.path.join('/cnhome/media', str(i.original_file)), 
        os.path.join(outDir, fname))


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


