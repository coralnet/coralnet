from abc import ABCMeta

from django.contrib.auth.models import Group
from django.core import mail
from django.core.files.base import ContentFile
from django.test import override_settings
from django.urls import reverse

from lib.tests.utils import BasePermissionTest
from sources.models import Source
from ..models import LabelGroup, Label
from .utils import LabelTest


class NewLabelPermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.create_labels(cls.user, ['A', 'B'], 'GroupA')

    def test_label_new(self):
        url = reverse('label_new')
        template = 'labels/label_new.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_label_new_ajax(self):
        url = reverse('label_new_ajax')

        self.assertPermissionLevel(
            url, self.SIGNED_IN, is_json=True, post_data={},
            deny_type=self.REQUIRE_LOGIN)


class EditLabelPermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Create labels and group
        labels = cls.create_labels(cls.user, ['A', 'B', 'C'], "Group1")

        cls.source1 = cls.create_source(cls.user)
        cls.create_labelset(
            cls.user, cls.source1, labels.filter(name__in=['A', 'B']))
        cls.source2 = cls.create_source(cls.user)
        cls.create_labelset(
            cls.user, cls.source2, labels.filter(name__in=['A', 'B']))
        cls.source3 = cls.create_source(cls.user)
        cls.create_labelset(
            cls.user, cls.source3, labels.filter(name__in=['C']))

        label_b = labels.get(name='B')
        label_b.verified = True
        label_b.save()

        cls.url = reverse('label_edit', args=[labels.get(name='A').pk])
        cls.url_verified = reverse('label_edit', args=[label_b.pk])

    def test_anonymous(self):
        self.assertPermissionDenied(self.url, None)

    def test_admin_of_one_source_using_the_label(self):
        user_admin_one = self.create_user()
        self.add_source_member(
            self.user, self.source1,
            user_admin_one, Source.PermTypes.ADMIN.code)

        # Must be admin of all sources using the label, not just one.
        self.assertPermissionDenied(self.url, user_admin_one)

    def test_editor_of_all_sources_using_the_label(self):
        user_editor_both = self.create_user()
        self.add_source_member(
            self.user, self.source1,
            user_editor_both, Source.PermTypes.EDIT.code)
        self.add_source_member(
            self.user, self.source2,
            user_editor_both, Source.PermTypes.EDIT.code)

        # Edit isn't enough, must be admin.
        self.assertPermissionDenied(self.url, user_editor_both)

    def test_admin_of_all_sources_using_the_label(self):
        user_admin_both = self.create_user()
        self.add_source_member(
            self.user, self.source1,
            user_admin_both, Source.PermTypes.ADMIN.code)
        self.add_source_member(
            self.user, self.source2,
            user_admin_both, Source.PermTypes.ADMIN.code)

        self.assertPermissionGranted(
            self.url, user_admin_both, template='labels/label_edit.html')

    def test_admin_of_all_sources_using_verified_label(self):
        user_admin_both = self.create_user()
        self.add_source_member(
            self.user, self.source1,
            user_admin_both, Source.PermTypes.ADMIN.code)
        self.add_source_member(
            self.user, self.source2,
            user_admin_both, Source.PermTypes.ADMIN.code)

        # Being source admin isn't enough for verified labels.
        self.assertPermissionDenied(self.url_verified, user_admin_both)

    def test_labelset_committee_member(self):
        user_committee_member = self.create_user()
        user_committee_member.groups.add(
            Group.objects.get(name="Labelset Committee"))

        # Committee members can edit verified labels.
        self.assertPermissionGranted(
            self.url_verified, user_committee_member,
            template='labels/label_edit.html')

    def test_superuser(self):
        self.assertPermissionGranted(
            self.url_verified, self.superuser,
            template='labels/label_edit.html')


class NewEditLabelBaseTest(LabelTest, metaclass=ABCMeta):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.user_committee_member = cls.create_user()
        cls.user_committee_member.groups.add(
            Group.objects.get(name="Labelset Committee"))

        # Create labels and groups
        cls.group1 = cls.create_label_group("Group1")
        cls.group2 = cls.create_label_group("Group2")
        cls.create_label(cls.user, "Label A", 'A', cls.group1)
        cls.create_label(cls.user, "Label B", 'B', cls.group1)

        # Ensure cls.user 'owns' the labels, by being the admin of every
        # source using those labels.
        cls.source = cls.create_source(cls.user)
        cls.create_labelset(
            cls.user, cls.source, Label.objects.all())

    def submit_and_assert_creation(
            self, user=None, expected_error=None, **params):
        """
        Attempt to create a label through the non-Ajax new label view,
        and assert that it goes as expected.
        """
        post_data = dict(
            name="Label C",
            default_code='C',
            group=self.group1.pk,
            description="Description\ngoes here.",
            # A new filename will be generated, and the uploaded
            # filename will be discarded, so this filename doesn't matter.
            thumbnail=self.sample_image_as_file('_.png'),
        )
        post_data.update(params)

        old_count = Label.objects.all().count()

        self.client.force_login(user or self.user)
        response = self.client.post(
            reverse('label_new'),
            data=post_data, follow=True)

        if expected_error:

            self.assertContains(
                response, expected_error,
                msg_prefix="Response should have the expected error")
            self.assertEqual(
                old_count, Label.objects.all().count(),
                msg="Label count should NOT have gone up")

        else:

            self.assertContains(
                response, "Label successfully created.",
                msg_prefix="Response should have the success message")
            self.assertEqual(
                old_count + 1, Label.objects.all().count(),
                msg="Label count should have gone up")
            self.assertIsNotNone(
                self.get_label(post_data['default_code']),
                msg="Label creation should have gone through")

        return response

    def submit_creation_ajax(self, user=None, **params):
        """Attempt to create a label through the Ajax new label view."""
        post_data = dict(
            name="Label C",
            default_code='C',
            group=self.group1.pk,
            description="Description\ngoes here.",
            # A new filename will be generated, and the uploaded
            # filename will be discarded, so this filename doesn't matter.
            thumbnail=self.sample_image_as_file('_.png'),
        )
        post_data.update(params)

        self.client.force_login(user or self.user)
        response = self.client.post(
            reverse('label_new_ajax'),
            data=post_data, follow=True)
        return response

    def submit_and_assert_creation_ajax(
            self, user=None, expected_error=None, **params):
        """
        Attempt to create a label through the Ajax new label view,
        and assert that it goes as expected.
        Note that the response is JSON if there's an error, HTML otherwise.
        """
        old_count = Label.objects.all().count()
        response = self.submit_creation_ajax(user=user, **params)

        if expected_error:

            self.assertEqual(
                response['Content-Type'], 'application/json',
                msg="Response should be JSON")
            self.assertEqual(
                response.json()['error'],
                expected_error,
                msg="Response should have the expected error")
            self.assertEqual(
                old_count, Label.objects.all().count(),
                msg="Label count should NOT have gone up")

        else:

            self.assertEqual(
                response['Content-Type'], 'text/html; charset=utf-8',
                msg="Response should be HTML")
            self.assertEqual(
                old_count + 1, Label.objects.all().count(),
                msg="Label count should have gone up")
            # Submitted default code: If in params, then it's that. Else, it's
            # the value in the default post data.
            default_code = params.get('default_code', 'C')
            self.assertIsNotNone(
                self.get_label(default_code),
                msg="Label creation should have gone through")

        return response

    @staticmethod
    def _field_value_as_post_param(label, field_name):
        """
        Convert `group` model objects to pks so they can be compared to
        submitted post params.
        Do nothing with string fields.
        `thumbnail` field doesn't work here, but we assert on that field
        differently anyway.
        """
        value = getattr(label, field_name)
        if field_name == 'group':
            value = value.pk
        return value

    def submit_edit(self, user=None, **params):
        """Attempt to edit Label A through the label edit view."""
        post_data = dict(
            name="Label A",
            default_code='A',
            group=self.get_label('A').group.pk,
            description=self.get_label('A').description,
        )
        post_data.update(params)

        self.client.force_login(user or self.user)
        response = self.client.post(
            reverse('label_edit', args=[self.get_label('A').pk]),
            data=post_data, follow=True)
        return response

    def submit_and_assert_edit(
            self, user=None, expected_error=None, **params):
        """
        Attempt to edit Label A through the label edit view, and assert
        that it goes as expected.
        """
        old_label = self.get_label('A')
        response = self.submit_edit(user=user, **params)

        if expected_error:

            self.assertContains(
                response, expected_error,
                msg_prefix="Response should have the expected error")

            # Check any of the passed params against the label's current
            # field value to ensure that the edit didn't go through.
            # This probably won't work with a `thumbnail` param, though.
            any_param_key, _ = params.popitem()
            self.assertEqual(
                getattr(Label.objects.get(pk=old_label.pk), any_param_key),
                getattr(old_label, any_param_key),
                "Edit should NOT have gone through")

        else:

            self.assertContains(
                response, "Label successfully edited.",
                msg_prefix="Response should have the success message")

            any_param_key, param_value = params.popitem()
            self.assertEqual(
                self._field_value_as_post_param(
                    Label.objects.get(pk=old_label.pk), any_param_key),
                param_value,
                "Edit should have gone through")

        return response


class LabelCreationGeneralTest(NewEditLabelBaseTest):
    """
    Test label creation in general.
    """
    @override_settings(LABELSET_COMMITTEE_EMAIL='labels@example.com')
    def test_label_creation_ajax(self):
        """Successfully create a new label."""
        self.client.force_login(self.user)
        self.client.post(reverse('label_new_ajax'), dict(
            name="CCC",
            default_code='C',
            group=LabelGroup.objects.get(code='Group1').pk,
            description="Species C.",
            # A new filename will be generated, and this uploaded
            # filename will be discarded, so it doesn't matter.
            thumbnail=self.sample_image_as_file('_.png'),
        ))

        # Check that the label was created, and has the expected field values
        label = Label.objects.get(name="CCC")
        self.assertEqual(label.default_code, 'C')
        self.assertEqual(label.group.code, 'Group1')
        self.assertEqual(label.description, "Species C.")
        self.assertIsNotNone(label.thumbnail)
        self.assertEqual(label.verified, False)
        self.assertEqual(label.created_by_id, self.user.pk)

        # Check that an email was sent out
        self.assertEqual(len(mail.outbox), 1)
        label_email = mail.outbox[-1]
        # Check recipients
        self.assertEqual(len(label_email.to), 1)
        self.assertEqual(label_email.to[0], 'labels@example.com')
        self.assertEqual(len(label_email.cc), 1)
        self.assertEqual(label_email.cc[0], self.user.email)
        # Contents should have the creating user, label name, and link
        # to label details
        self.assertIn(self.user.username, label_email.body)
        self.assertIn("CCC", label_email.body)
        self.assertIn(
            reverse('label_main', args=[label.pk]), label_email.body)

    def test_label_creation(self):
        """Successfully create a new label."""
        self.client.force_login(self.user)
        self.client.post(reverse('label_new'), dict(
            name="CCC",
            default_code='C',
            group=LabelGroup.objects.get(code='Group1').pk,
            description="Species C.",
            # A new filename will be generated, and the uploaded
            # filename will be discarded, so it doesn't matter.
            thumbnail=self.sample_image_as_file('_.png'),
        ))

        # Check that the label was created, and has the expected field values
        label = Label.objects.get(name="CCC")
        self.assertEqual(label.default_code, 'C')
        self.assertEqual(label.group.code, 'Group1')
        self.assertEqual(label.description, "Species C.")
        self.assertIsNotNone(label.thumbnail)
        self.assertEqual(label.verified, False)
        self.assertEqual(label.created_by_id, self.user.pk)


class GeneralFieldsTest(NewEditLabelBaseTest):
    """
    Test setting / validation of the Label fields common to the new and
    edit forms.
    """
    def test_name_required(self):
        """Name is a required field."""
        error_message = "This field is required."

        params = dict(name="")

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Name: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_name_too_long(self):
        """Name exceeds max length."""
        error_message = (
            "Ensure this value has at most 45 characters (it has 46).")

        params = dict(name="a"*46)

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Name: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_name_same(self):
        """
        Not changing the name.
        Should not invoke any duplicate-name checking logic.
        """
        self.submit_and_assert_edit(name="Label A")

    def test_name_change_case_only(self):
        """
        Changing only the upper/lower case of the name.
        Should not invoke any duplicate-name checking logic.
        """
        self.submit_and_assert_edit(name="LABEL a")

    def test_name_change(self):
        """Changing name without any particular special conditions."""
        self.submit_and_assert_edit(name="Label Alpha")

    def test_name_conflict(self):
        """Name conflict with another label (case insensitive)."""
        error_message = (
            'There is already a label with the same name:'
            ' <a href="{url}" target="_blank">Label B</a>'.format(
                url=reverse('label_main', args=[self.get_label('B').pk])))

        # This name has different case from the current name, but it
        # should still bring up a name conflict.
        params = dict(name="LABEL B")

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Name: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_name_disallowed_characters(self):
        error_message = "You entered disallowed characters or punctuation."

        self.submit_and_assert_creation(
            name="CCA?", expected_error=error_message)

        self.submit_and_assert_creation_ajax(
            name="Tridacne géant",
            expected_error="Name: " + error_message)

        self.submit_and_assert_edit(
            name="Ｇalaxaura pacifica",
            expected_error=error_message)

    def test_default_code_required(self):
        """Default code is a required field."""
        error_message = "This field is required."

        params = dict(default_code="")

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Default Short Code: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_default_code_too_long(self):
        """Default code exceeds max length."""
        error_message = (
            "Ensure this value has at most 10 characters (it has 11).")

        params = dict(default_code="a"*11)

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Default Short Code: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_default_code_same(self):
        """
        Not changing the default code.
        Should not invoke any duplicate-name checking logic.
        """
        self.submit_and_assert_edit(default_code='A')

    def test_default_code_change_case_only(self):
        """
        Changing only the upper/lower case of the default code.
        Should not invoke any duplicate-name checking logic.
        """
        self.submit_and_assert_edit(default_code='a')

    def test_default_code_change(self):
        """Changing default code without any particular special conditions."""
        self.submit_and_assert_edit(default_code='Alpha')

    def test_default_code_conflict(self):
        """Default code conflict with another label (case insensitive)."""
        error_message = (
            'There is already a label with the same default code:'
            ' <a href="{url}" target="_blank">B</a>'.format(
                url=reverse('label_main', args=[self.get_label('B').pk])))

        # This code has different case from the current code, but it
        # should still bring up a code conflict.
        params = dict(default_code='b')

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Default Short Code: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_default_code_disallowed_characters(self):
        error_message = "You entered disallowed characters or punctuation."

        self.submit_and_assert_creation(
            default_code="don't_know",
            expected_error=error_message)

        self.submit_and_assert_creation_ajax(
            default_code="bryo,br",
            expected_error="Default Short Code: " + error_message)

        self.submit_and_assert_edit(
            default_code="porit<20",
            expected_error=error_message)

    def test_group_change(self):
        self.submit_and_assert_edit(group=self.group2.pk)

    def test_group_required(self):
        """Group is a required field."""
        error_message = "This field is required."

        params = dict(group="")

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Functional Group: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_description_change(self):
        self.submit_and_assert_edit(description="Another\ndescription")

    def test_description_required(self):
        """Description is a required field."""
        error_message = "This field is required."

        params = dict(description="")

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Description: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_description_too_long(self):
        error_message = (
            "Ensure this value has at most 2000 characters (it has 2001).")

        params = dict(description='a'*2001)

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Description: " + error_message, **params)

        self.submit_and_assert_edit(
            expected_error=error_message, **params)

    def test_thumbnail_change(self):
        original_filename = self.get_label('A').thumbnail.name

        response = self.submit_edit(
            thumbnail=self.sample_image_as_file('_.png'))

        self.assertContains(
            response, "Label successfully edited.",
            msg_prefix="Response should have the success message")
        # Check for a different thumbnail file, by checking filename.
        # This assumes the filenames are designed to not clash
        # (e.g. qoxibnwke9.jpg) rather than replace each other
        # (e.g. thumbnail-for-label-29.jpg).
        self.assertNotEqual(
            original_filename, self.get_label('A').thumbnail.name,
            msg="Editing the thumbnail should succeed.")

    def test_thumbnail_required_for_creation(self):
        """Thumbnail is a required field for creation only, not edit."""
        error_message = "This field is required."

        params = dict(thumbnail='')

        self.submit_and_assert_creation(
            expected_error=error_message, **params)

        self.submit_and_assert_creation_ajax(
            expected_error="Example image (thumbnail): " + error_message,
            **params)

        original_filename = self.get_label('A').thumbnail.name
        response = self.submit_edit(thumbnail='')
        self.assertContains(
            response, "Label successfully edited.",
            msg_prefix="Response should have the success message")
        self.assertEqual(
            original_filename, self.get_label('A').thumbnail.name,
            msg="Thumbnail file should be the same")

    def test_thumbnail_non_image(self):
        """Non-image file in the thumbnail field."""
        error_message = (
            "Upload a valid image. The file you uploaded was either"
            " not an image or a corrupted image.")

        # Need to create a new file on each request.
        self.submit_and_assert_creation(
            expected_error=error_message,
            thumbnail=ContentFile('some text', name='1.txt'))

        self.submit_and_assert_creation_ajax(
            expected_error="Example image (thumbnail): " + error_message,
            thumbnail=ContentFile('some text', name='1.txt'))

        self.submit_and_assert_edit(
            expected_error=error_message,
            thumbnail=ContentFile('some text', name='1.txt'))

    def test_thumbnail_scaled_down(self):
        """
        Dimensions should be scaled and trimmed to the standard size
        instead of keeping the original size.
        """
        params = dict(
            thumbnail=self.sample_image_as_file(
                '_.png',
                image_options=dict(
                    width=Label.THUMBNAIL_WIDTH+100,
                    height=Label.THUMBNAIL_HEIGHT+150,
                )))

        response = self.submit_edit(**params)
        self.assertContains(
            response, "Label successfully edited.",
            msg_prefix="Response should have the success message")

        label = self.get_label('A')
        self.assertLessEqual(
            label.thumbnail.width, Label.THUMBNAIL_WIDTH,
            "Width should be scaled down")
        self.assertLessEqual(
            label.thumbnail.height, Label.THUMBNAIL_HEIGHT,
            "Height should be scaled down")


class VerifiedDuplicateFieldsTest(NewEditLabelBaseTest):
    """
    Test setting / validation of the verified and duplicate fields.
    """
    def test_verified_change(self):
        self.submit_edit(
            user=self.user_committee_member,
            verified=True)

        self.assertEqual(
            self.get_label('A').verified, True,
            msg="Editing the verified field should succeed.")

    def test_duplicate_change(self):
        # Must verify B to make it a candidate for a duplicate pointer
        label_B = self.get_label('B')
        label_B.verified = True
        label_B.save()

        response = self.submit_edit(
            user=self.user_committee_member,
            duplicate=label_B.pk)

        self.assertContains(response, "Label successfully edited.")
        self.assertEqual(
            self.get_label('A').duplicate.pk, self.get_label('B').pk)

    def test_verified_requires_permission(self):
        # Non committee member
        self.submit_edit(
            user=self.user,
            verified=True)

        # Not changed
        self.assertEqual(self.get_label('A').verified, False)

    def test_cant_verify_on_creation(self):
        """Can't set label as verified upon creation."""
        old_count = Label.objects.all().count()
        response = self.submit_creation_ajax(verified=True)

        self.assertEqual(
            response['Content-Type'], 'text/html; charset=utf-8',
            msg="Response should be HTML")
        self.assertEqual(
            old_count + 1, Label.objects.all().count(),
            msg="Label count should have gone up")

        self.assertEqual(
            self.get_label('C').verified, False,
            msg="Verified param should have been ignored")

    def test_duplicate_requires_permission(self):
        # Must verify B to make it a candidate for a duplicate pointer
        label_B = self.get_label('B')
        label_B.verified = True
        label_B.save()

        response = self.submit_edit(
            user=self.user,
            duplicate=label_B.pk)

        # Still expect to show success, but with the duplicate field ignored
        self.assertContains(response, "Label successfully edited.")

        # Not changed
        self.assertEqual(self.get_label('A').duplicate, None)

    def test_duplicate_cant_point_to_unverified(self):
        label_B = self.get_label('B')
        label_B.verified = False
        label_B.save()

        response = self.submit_edit(
            user=self.user_committee_member,
            duplicate=label_B.pk)

        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(
            response,
            "Select a valid choice. That choice is not one of the available"
            " choices.")

        # Not changed
        self.assertEqual(self.get_label('A').duplicate, None)

    def test_duplicate_cant_be_verified(self):
        label_B = self.get_label('B')
        label_B.verified = True
        label_B.save()

        response = self.submit_edit(
            user=self.user_committee_member,
            verified=True,
            duplicate=label_B.pk)

        self.assertContains(response, "Please correct the errors below.")
        self.assertContains(
            response, "A label can not both be a Duplicate and Verified.")

        # Not changed
        self.assertEqual(self.get_label('A').duplicate, None)
