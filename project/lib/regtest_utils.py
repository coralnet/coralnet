import csv
import sys
import boto

import os.path as osp

from io import StringIO

from django.core import management
from django.core.files.base import ContentFile
from django.conf import settings
from django.test.client import Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from .tests.utils import ClientTest

from images.models import Source
from labels.models import LabelGroup, Label, LabelSet, LocalLabel
from lib.utils import direct_s3_read

User = get_user_model()


class VisionBackendRegressionTest(ClientTest):
    """
    Management class for vision backend regression tests.
    This class relies on a specific regression test fixture layout.
    """

    def __init__(self, source_id, name_suffix):

        self.client = Client()
        # Create a superuser.
        if not User.objects.filter(username='superuser').exists():
            management.call_command(
                'createsuperuser',
                '--noinput', username='superuser',
                email='superuser@example.com', verbosity=0)
        self.user = User.objects.get(username='superuser')

        # Create other users.
        for username in [settings.IMPORTED_USERNAME, settings.ROBOT_USERNAME, settings.ALLEVIATE_USERNAME]:
            if not User.objects.filter(username=username).exists():
                user = User(username=username)
                user.save()
        
        # Setup path to source_id fixtures.
        self.ann_file = 'sources/s{}/imdict.p'.format(source_id)
        self.im_dir = 'sources/s{}/imgs/'.format(source_id)
        self.source_name = 'REGTEST_CUSTOM_SOURCE_{}_{}'.format(source_id, name_suffix)
        self.global_labelfile = 'labels.json'

        # List images.
        conn = boto.connect_s3(
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY
        )
        bucket = conn.get_bucket(settings.REGTEST_BUCKET)
        imfiles = bucket.list(prefix=self.im_dir)
        self.imfiles = [member.name for member in imfiles][1:]  # Starting from 1 to skip root folder.

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
        self.upload_images(len(self.imfiles), with_anns=with_anns)

    def upload_images(self, nbr, with_anns=True):
        """
        Upload INPUT nbr images.
        """
        for i in range(nbr):
            self.upload_image(with_anns=with_anns)

    def upload_image(self, with_anns=True):
        """
        Upload an image.
        """
        if self.cur + 1 == len(self.imfiles):
            print("Already uploaded all images.")
            return
        img = self.imfiles[self.cur]

        sys.stdout.write(str(self.cur) + ', ')
        sys.stdout.flush()
        
        self.cur += 1
        self._upload_image(img)
        
        if with_anns:
            anns = self.anns[osp.basename(img)]
            self._upload_annotations(osp.basename(img), anns)

    def _setup_source(self):
        """
        Creates source and labelset. Also creates global labels if needed.
        """
        print("Setting up: {}".format(self.source_name))
        if Source.objects.filter(name=self.source_name).exists():
            Source.objects.filter(name=self.source_name).delete()
        
        # Create new source.
        self.source = self.create_source()
        
        # Find all labelnames in exported annotation file.
        anns = direct_s3_read(self.ann_file, 'pickle', bucketname=settings.REGTEST_BUCKET)
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
        (_, lbls) = direct_s3_read(self.global_labelfile, 'json', bucketname=settings.REGTEST_BUCKET)

        codedict = dict()
        for lbl in lbls:
            codedict[lbl[0]] = lbl[1]
        self.codedict = codedict

        return

    def _parse_annotations(self):
        """
        Parses exported annotation file and returns a dictionary ready to be uploaded.
        """
        anns = direct_s3_read(self.ann_file, 'pickle', bucketname=settings.REGTEST_BUCKET)
        new_anns = dict()
        for im_name in anns.keys():
            new_anns[im_name] = []
            for [labelname, row, col] in anns[im_name][0]:
                labelcode = self.codedict[labelname]
                new_anns[im_name].append((row, col, labelcode))
        
        self.anns = new_anns

    def _add_global_labels(self, labellist):
        """
        Imports all labels and groups from a json file. See 
        "vision_backend/scripts.export_labels_json".
        """
        
        (grps, lbls) = direct_s3_read(self.global_labelfile, 'json', bucketname=settings.REGTEST_BUCKET)

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

    def _upload_annotations(self, im_file, anns):
        """
        Annotations on all specified points.
        """

        def preview_anns(csv_file):
            return self.client.post(
                reverse('upload_annotations_csv_preview_ajax', args=[self.source.pk]),
                {'csv_file': csv_file},
            )

        def upload_anns():
            return self.client.post(
                reverse('upload_annotations_ajax', args=[self.source.pk]),
            ) 

        self.client.force_login(self.user)

        with StringIO() as stream:
            writer = csv.writer(stream)
            writer.writerow(['Name', 'Row', 'Column', 'Label'])
            for ann in anns:
                writer.writerow([im_file, ann[0], ann[1], ann[2]])
            
            f = ContentFile(stream.getvalue(), name='ann_upload' + '.csv')
            preview_response = preview_anns(f)
            upload_response = upload_anns()

        self.client.logout()

    def _upload_image(self, im_file):
        """
        Upload a data image.
        :param im_file: path to the image file to upload.
        :return: The new image object.
        """
        post_dict = dict()        
        post_dict['file'] = ContentFile(direct_s3_read(im_file, 'none', bucketname=settings.REGTEST_BUCKET),
                                        name=im_file)
        post_dict['name'] = osp.basename(im_file)

        # Send the upload form
        self.client.force_login(self.user)
        reponse = self.client.post(
            reverse('upload_images_ajax', kwargs={'source_id': self.source.id}),
            post_dict,
        )
        self.client.logout()
