import csv
from io import StringIO
import json
import pickle
import posixpath
import sys

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test.client import Client
from django.urls import reverse
from storages.backends.s3 import S3Storage

from labels.models import LabelGroup, Label, LabelSet, LocalLabel
from sources.models import Source
from vision_backend.common import Extractors
from .tests.utils import ClientTest

User = get_user_model()


class VisionBackendRegressionTest(ClientTest):
    """
    Management class for vision backend regression tests.
    This class relies on a specific regression test fixture layout.
    """

    def __init__(self, source_id, name_suffix, use_vgg16):

        self.use_vgg16 = use_vgg16

        self.client = Client()
        self.regtest_storage = S3Storage(
            bucket_name=settings.REGTEST_BUCKET, location='')

        # Get any superuser. We'll assume one exists (if it doesn't, this'll
        # get an error).
        superusers = User.objects.filter(is_superuser=True).order_by('pk')
        self.user = superusers.first()

        # Setup path to source_id fixtures.
        self.ann_file = f'sources/s{source_id}/imdict.p'
        self.source_name = f'REGTEST_CUSTOM_SOURCE_{source_id}_{name_suffix}'
        self.global_labelfile = 'labels.json'

        # List images.
        image_dir = f'sources/s{source_id}/imgs/'
        _, image_filenames = self.regtest_storage.listdir(image_dir)
        image_filenames.sort()
        # Starting from 1 to skip root folder.
        self.image_filepaths = [
            image_dir + filename for filename in image_filenames[1:]]

        # Create source and label-set.
        self._setup_source()

        # Load annotations to memory and prepare for upload.
        self._make_labelcode_dict()
        self._parse_annotations()

        # Initialize the image counter of how many images have been uploaded.
        self.cur = 0

    def upload_all_images(self, with_anns=True):
        """
        Upload all images available in fixtures.
        """
        self.upload_images(len(self.image_filepaths), with_anns=with_anns)

    def upload_images(self, number_of_images):
        """
        Upload number_of_images images and return the filepaths.
        """
        return [self.upload_image() for _ in range(number_of_images)]

    def upload_image(self):
        """
        Upload an image.
        """
        if self.cur + 1 == len(self.image_filepaths):
            print("-> Already uploaded all images.")
            return
        image_filepath = self.image_filepaths[self.cur]

        sys.stdout.write(str(self.cur) + ', ')
        sys.stdout.flush()

        self.cur += 1
        self._upload_image(image_filepath)
        return image_filepath

    def upload_anns(self, image_filepath):
        """ Uploads anns """
        image_filename = posixpath.basename(image_filepath)
        anns = self.anns[image_filename]
        self._upload_annotations(image_filename, anns)

    def _setup_source(self):
        """
        Creates source and labelset. Also creates global labels if needed.
        """
        print(f"-> Setting up: {self.source_name}")
        try:
            source = Source.objects.get(name=self.source_name)
        except Source.DoesNotExist:
            pass
        else:
            print("-> Found previous source, deleting that one.")
            self.client.force_login(self.user)
            self.client.post(
                reverse('source_admin', args=[source.pk]),
                dict(Delete='Delete'))
            self.client.logout()

        # Create new source.
        self.source = self.create_source()

        # Find all label-names in exported annotation file.
        with self.regtest_storage.open(self.ann_file) as f:
            anns = pickle.load(f)
        labellist = set()
        for key in anns.keys():
            for [labelname, _, _] in anns[key][0]:
                labellist.add(labelname)

        # Create global labels if needed
        self._add_global_labels(labellist)

        # Create labelset for this source.
        labelset = LabelSet()
        labelset.save()
        self.source.labelset = labelset
        self.source.save()
        for name in labellist:
            label = Label.objects.get(name=name)
            LocalLabel(
                global_label=label,
                code=label.default_code,
                labelset=labelset
            ).save()

    def create_source(self):
        """
        Creates a source.
        """
        post_dict = dict()
        post_dict.update(self.source_defaults)
        post_dict['name'] = self.source_name
        if self.use_vgg16:
            post_dict['feature_extractor_setting'] = Extractors.VGG16.value

        self.client.force_login(self.user)
        self.client.post(reverse('source_new'), post_dict)
        self.client.logout()
        return Source.objects.get(name=self.source_name)

    def _make_labelcode_dict(self):
        """
        Returns a dictionary which maps label names to label code.
        This is needed b/c the upload form needs codes but the fixtures lists
        label names.
        """
        with self.regtest_storage.open(self.global_labelfile) as f:
            (_, lbls) = json.load(f)

        codedict = dict()
        for lbl in lbls:
            codedict[lbl[0]] = lbl[1]
        self.codedict = codedict

        return

    def _parse_annotations(self):
        """
        Parses exported annotation file and returns a dictionary ready to be uploaded.
        """
        with self.regtest_storage.open(self.ann_file) as f:
            anns = pickle.load(f)
        new_anns = dict()
        for image_filename in anns.keys():
            new_anns[image_filename] = []
            for [labelname, row, col] in anns[image_filename][0]:
                labelcode = self.codedict[labelname]
                new_anns[image_filename].append((row, col, labelcode))

        self.anns = new_anns

    def _add_global_labels(self, labellist):
        """
        Imports all labels and groups from a json file. See
        "vision_backend/scripts.export_labels_json".
        """
        with self.regtest_storage.open(self.global_labelfile) as f:
            (grps, lbls) = json.load(f)

        for grp in grps:
            self._add_functional_group(grp[0], grp[1])

        for lbl in lbls:
            if lbl[0] in labellist:
                self._add_label(lbl[0], lbl[1], lbl[2])

    @staticmethod
    def _add_functional_group(name, code):
        """
        Adds functional group to DB.
        """
        if LabelGroup.objects.filter(name=name).count() > 0:
            return
        LabelGroup(
            name=name,
            code=code
        ).save()

    @staticmethod
    def _add_label(name, code, group):
        """
        Adds label to DB.
        """
        if Label.objects.filter(name=name).count() > 0:
            return
        Label(
            name=name,
            default_code=code,
            group=LabelGroup.objects.get(name=group)
        ).save()

    def _upload_annotations(self, image_filename, anns):
        """
        Annotations on all specified points.
        """

        def preview_anns(csv_file):
            return self.client.post(
                reverse('upload_annotations_csv_preview_ajax',
                        args=[self.source.pk]),
                {'csv_file': csv_file},
            )

        def upload_anns():
            return self.client.post(
                reverse('upload_annotations_csv_confirm_ajax',
                        args=[self.source.pk]),
            )

        self.client.force_login(self.user)

        with StringIO() as stream:
            writer = csv.writer(stream)
            writer.writerow(['Name', 'Row', 'Column', 'Label'])
            for ann in anns:
                writer.writerow([image_filename, ann[0], ann[1], ann[2]])

            f = ContentFile(stream.getvalue(), name='ann_upload' + '.csv')
            preview_anns(f)
            upload_anns()

        self.client.logout()

    def _upload_image(self, image_filepath):
        """
        Upload a data image.
        :param image_filepath: path to the image file to upload.
        :return: The new image object.
        """
        post_dict = dict(
            file=self.regtest_storage.open(image_filepath),
            name=posixpath.basename(image_filepath),
        )

        # Send the upload form
        self.client.force_login(self.user)
        self.client.post(reverse('upload_images_ajax',
                                 kwargs={'source_id': self.source.id}),
                         post_dict)
        self.client.logout()
