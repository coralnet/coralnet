from abc import ABCMeta

from django.urls import reverse

from lib.tests.utils import ClientTest
from ..models import LabelGroup, Label


# Abstract class
class LabelTest(ClientTest, metaclass=ABCMeta):

    @classmethod
    def create_label_group(cls, group_name):
        group = LabelGroup(name=group_name, code=group_name[:10])
        group.save()
        return group

    @classmethod
    def create_label(cls, user, name, default_code, group):
        cls.client.force_login(user)
        cls.client.post(
            reverse('label_new_ajax'),
            dict(
                name=name,
                default_code=default_code,
                group=group.pk,
                description="Description",
                # A new filename will be generated, and the uploaded
                # filename will be discarded, so this filename doesn't matter.
                thumbnail=cls.sample_image_as_file('_.png'),
            )
        )
        cls.client.logout()

        return Label.objects.get(name=name)

    @staticmethod
    def get_label(default_code):
        try:
            return Label.objects.get(default_code=default_code)
        except Label.DoesNotExist:
            return None
