import os
import json
import pickle
import random
import shutil
from images.models import Source, Point
from .models import Score
from labels.models import Label, LabelGroup, LabelSet, LocalLabel


def print_image_scores(image_id):
    """
    Print image scores to console. For debugging purposes.
    """
    points = Point.objects.filter(image_id = image_id).order_by('id')
    for enu, point in enumerate(points):
        print '===', enu, point.row, point.column, '==='
        for score in Score.objects.filter(point = point):
            print score.label, score.score


def export_labels_json(filename):
    """
    Exports all labels and groups to a json file. 
    Used to seed dev. machines with global labelset.
    """
    grps = []
    for grp in LabelGroup.objects.filter():
        grps.append((grp.name, grp.code))

    lbls = []
    for lbl in Label.objects.filter():
        lbls.append((lbl.name, lbl.default_code, lbl.group.name))

    with open(filename, 'w') as f:
        json.dump((grps, lbls), f)


def import_labels_json(filename):
    """
    Imports all labels and groups from a json file. See 
    "export_labels_json".
    """
    with open(filename) as f:
        (grps, lbls) = json.load(f)
    for grp in grps:
        add_functional_group(grp[0], grp[1])

    for lbl in lbls:
        add_label(lbl[0], lbl[1], lbl[2])        


def add_functional_group(name, code):
    """
    Adds functional group to DB.
    """
    if LabelGroup.objects.filter(name = name).count() > 0:
        return
    LabelGroup(
        name = name,
        code = code
    ).save()
    

def add_label(name, code, group):
    """
    Adds label to DB.
    """
    if Label.objects.filter(name = name).count() > 0:
        return
    Label(
        name = name,
        default_code = code,
        group = LabelGroup.objects.get(name = group)
    ).save()


def setup_source_for_import(annfile_path, sourcename):
    """
    Takes a file with annotations and creates a 
    source with a labelset containing all labels in annfile.
    """
    if not Source.objects.filter(name = sourcename).exists():
        s = Source(
            name = sourcename,
            image_annotation_area = '0;100;0;100',
            default_point_generation_method = 'm_11',
        )
        labelset = LabelSet()
        labelset.save()
        s.labelset = labelset
        s.save()
     
    # Find all labelnames in exported annotation file   
    f = open(annfile_path, 'r')
    anns = pickle.load(f)
    labellist = set()
    for key in anns.keys():
        for [labelname, row, col] in anns[key][0]:
            labellist.add(labelname)

    # Create them for this source
    labelset = LabelSet.objects.get(source__name = sourcename)
    for name in labellist:
        print name
        label = Label.objects.get(name = name)
        LocalLabel(
            global_label = label,
            code = label.default_code,
            labelset = labelset
        ).save()


def chunkify_source_for_image_import(chunklist, source_path):
    f = open(os.path.join(source_path, 'imdict.p'), 'r')
    anns = pickle.load(f)
    imlist = anns.keys()
    random.shuffle(imlist)
    if sum(chunklist)>len(imlist):
        raise ValueError('not enough images in source (asked {}, has {})'.format(sum(chunklist), len(imlist)))
    pos = -1
    for chunk in chunklist:
        chunkname = 'chunk{}'.format(chunk)
        shutil.rmtree(os.path.join(source_path, chunkname), ignore_errors=True)
        os.mkdir(os.path.join(source_path, chunkname))
        f = open(os.path.join(source_path, chunkname, 'anns.csv'), 'w')
        f.write('Name, Row, Column, Label\n')
        for i in range(chunk):
            pos += 1
            im = imlist[pos]
            for [label, row, col] in anns[im][0]:
                code = Label.objects.get(name = label).default_code
                f.write('{}, {}, {}, {}\n'.format(im, row, col, code))
            shutil.copyfile(
                os.path.join(source_path, 'imgs', im),
                os.path.join(source_path, chunkname, im))


def export_images_and_annotations(source_idlist, outdir):
    """
    Exports all images and annotations of a source.
    """

    for source_id in source_idlist:
        this_dir = os.path.join(outdir, 's{}'.format(source_id))
        os.mkdir(this_dir)
        os.mkdir(os.path.join(this_dir, 'imgs'))
        imdict = {} 
        source = Source.objects.get(id = source_id)
        for im in source.get_all_images():
            
            # Special check for MLC. Do not want the imgs from 2008!!!!
            if source_id == 16 and im.metadata.photo_date.year == 2008:
                continue
            if not im.status.annotatedByHuman:
                continue
            
            annlist = []
            for a in im.annotation_set.filter():
                annlist.append((a.label.name, a.point.row, a.point.column))
            imdict[im.metadata.name] = (annlist, im.height_cm())
            copyfile(os.path.join('/cnhome/media', str(im.original_file)), os.path.join(this_dir, 'imgs', im.metadata.name))
        pickle.dump(imdict, open(os.path.join(this_dir, 'imdict.p'), 'wb'))
