from bs4 import BeautifulSoup
from django.urls import reverse
from django.utils.html import escape

from calcification.models import CalcifyRateTable
from jobs.tasks import run_scheduled_jobs_until_empty
from lib.tests.utils import BasePermissionTest
from ..models import Label
from .utils import LabelTest


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')
        cls.create_labelset(cls.user, cls.source, cls.labels)

    def test_labelset_add_search_ajax(self):
        url = reverse('labelset_add_search_ajax') + '?search=abc'
        template = 'labels/label_box_container.html'

        # This view is unusual because it's Ajax, yet responds with HTML.
        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_labelset_duplicates(self):
        url = reverse('labelset_duplicates')
        template = 'labels/list_duplicates.html'

        self.assertPermissionLevel(
            url, self.SIGNED_IN, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_labelset_main(self):
        url = reverse('labelset_main', args=[self.source.pk])
        template = 'labels/labelset_main.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)

    def test_labelset_add(self):
        url = reverse('labelset_add', args=[self.source.pk])
        template = 'labels/labelset_add.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)

    def test_labelset_edit(self):
        url = reverse('labelset_edit', args=[self.source.pk])
        template = 'labels/labelset_edit.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SOURCE_ADMIN, template=template)


class LabelsetCreateTest(LabelTest):
    """
    Test the new labelset page.
    """
    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user()

        # Create source
        cls.source = cls.create_source(cls.user)

        # Create labels and group
        cls.group = cls.create_label_group("Group1")
        cls.create_label(cls.user, "Label A", 'A', cls.group)
        cls.create_label(cls.user, "Label B", 'B', cls.group)
        cls.create_label(cls.user, "Label C", 'C', cls.group)

        cls.url = reverse('labelset_add', args=[cls.source.pk])

    def test_success(self):
        """Successfully create a new labelset."""

        # These are the labels we'll try putting into the labelset.
        label_pks = [
            Label.objects.get(name=name).pk
            for name in ["Label A", "Label B"]
        ]

        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            dict(label_ids=','.join(str(pk) for pk in label_pks)),
            follow=True,
        )
        self.assertContains(response, "Labelset successfully created.")

        url = reverse('labelset_main', args=[self.source.pk])
        self.assertRedirects(response, url)

        # Check the new labelset for the expected labels.
        self.source.refresh_from_db()
        # Check codes.
        self.assertSetEqual(
            {label.code for label in self.source.labelset.get_labels()},
            {'A', 'B'},
        )
        # Check foreign keys to globals.
        self.assertSetEqual(
            {label.pk for label in self.source.labelset.get_globals()},
            set(label_pks),
        )

    def test_no_labels(self):
        """No labels -> error."""
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            dict(label_ids=''),
        )
        self.assertContains(response, "You must select one or more labels.")

        self.source.refresh_from_db()
        self.assertIsNone(self.source.labelset)


class LabelsetAddRemoveTest(LabelTest):
    """
    Test adding/removing labels from a labelset.
    """
    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user()

        # Create labels and group
        cls.group = cls.create_label_group("Group1")
        cls.create_label(cls.user, "Label A", 'A', cls.group)
        cls.create_label(cls.user, "Label B", 'B', cls.group)
        cls.create_label(cls.user, "Label C", 'C', cls.group)
        cls.create_label(cls.user, "Label D", 'D', cls.group)
        cls.create_label(cls.user, "Label E", 'E', cls.group)

        # Create source and labelset
        cls.source = cls.create_source(
            cls.user,
            default_point_generation_method=dict(type='simple', points=1))
        cls.create_labelset(cls.user, cls.source, Label.objects.filter(
            default_code__in=['A', 'B', 'C']))

        cls.url = reverse('labelset_add', args=[cls.source.pk])

    def test_add(self):
        # Add D E
        label_pks = [
            Label.objects.get(default_code=default_code).pk
            for default_code in ['A', 'B', 'C', 'D', 'E']
        ]
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            dict(label_ids=','.join(str(pk) for pk in label_pks)),
            follow=True,
        )
        self.assertContains(response, "Labelset successfully changed.")

        # Check the edited labelset for the expected labels.
        self.source.labelset.refresh_from_db()
        self.assertSetEqual(
            set(self.source.labelset.get_labels().values_list(
                'code', flat=True)),
            {'A', 'B', 'C', 'D', 'E'},
        )

    def test_remove(self):
        # Remove B C
        label_pks = [
            Label.objects.get(default_code=default_code).pk
            for default_code in ['A']
        ]
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            dict(label_ids=','.join(str(pk) for pk in label_pks)),
            follow=True,
        )
        self.assertContains(response, "Labelset successfully changed.")

        # Check the edited labelset for the expected labels.
        self.source.labelset.refresh_from_db()
        self.assertSetEqual(
            set(self.source.labelset.get_labels().values_list(
                'code', flat=True)),
            {'A'},
        )

    def test_add_and_remove(self):
        # Remove A B, add D E
        label_pks = [
            Label.objects.get(default_code=default_code).pk
            for default_code in ['C', 'D', 'E']
        ]
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            dict(label_ids=','.join(str(pk) for pk in label_pks)),
            follow=True,
        )
        self.assertContains(response, "Labelset successfully changed.")

        # Check the edited labelset for the expected labels.
        self.source.labelset.refresh_from_db()
        self.assertSetEqual(
            set(self.source.labelset.get_labels().values_list(
                'code', flat=True)),
            {'C', 'D', 'E'},
        )

    def test_cant_remove_label_with_confirmed_annotations(self):
        # Annotate with C
        img = self.upload_image(self.user, self.source)
        self.add_annotations(self.user, img, {1: 'C'})

        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertSetEqual(
            set(response.context['label_ids_in_confirmed_annotations']),
            {Label.objects.get(default_code='C').pk},
            "Context variable that controls which labels are removable on the"
            " form should have the expected value")

        # Try to remove C
        label_pks = [
            Label.objects.get(default_code=default_code).pk
            for default_code in ['A', 'B']
        ]
        response = self.client.post(
            self.url,
            dict(label_ids=','.join(str(pk) for pk in label_pks)),
            follow=True,
        )

        self.assertContains(
            response,
            escape(
                "The label 'Label C' is marked for removal from the"
                " labelset, but we can't remove it because the source"
                " still has confirmed annotations with this label."),
            msg_prefix="Response should contain the expected error message")

        self.source.labelset.refresh_from_db()
        self.assertSetEqual(
            set(self.source.labelset.get_labels().values_list(
                'code', flat=True)),
            {'A', 'B', 'C'},
            "Labelset changes shouldn't be saved to the DB")

    def test_can_remove_label_with_only_unconfirmed_annotations(self):
        # Robot-annotate with C
        img = self.upload_image(self.user, self.source)
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, img, {1: 'C'})

        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertSetEqual(
            set(response.context['label_ids_in_confirmed_annotations']),
            set(),
            "Context variable that controls which labels are removable on the"
            " form should have the expected value")

        # Remove C
        label_pks = [
            Label.objects.get(default_code=default_code).pk
            for default_code in ['A', 'B']
        ]
        response = self.client.post(
            self.url,
            dict(label_ids=','.join(str(pk) for pk in label_pks)),
            follow=True,
        )
        self.assertContains(
            response, "Labelset successfully changed.",
            msg_prefix="Form submission should succeed")

        self.source.labelset.refresh_from_db()
        self.assertSetEqual(
            set(self.source.labelset.get_labels().values_list(
                'code', flat=True)),
            {'A', 'B'},
            "Labelset changes should be saved to the DB")

    def test_labelset_change_resets_backend_for_source(self):
        # Create robot and robot annotations
        img = self.upload_image(self.user, self.source)
        robot = self.create_robot(self.source)
        self.add_robot_annotations(robot, img, {1: 'C'})

        # Remove A
        label_pks = [
            Label.objects.get(default_code=default_code).pk
            for default_code in ['B', 'C']
        ]

        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            dict(label_ids=','.join(str(pk) for pk in label_pks)),
            follow=True,
        )
        # Let the backend-reset run
        run_scheduled_jobs_until_empty()

        self.assertContains(
            response, "Labelset successfully changed.",
            msg_prefix="Form submission should succeed")

        self.assertEqual(
            self.source.score_set.count(), 0, "Scores should be deleted")
        self.assertEqual(
            self.source.classifier_set.count(), 0,
            "Classifier should be deleted")
        self.assertEqual(
            self.source.annotation_set.unconfirmed().count(), 0,
            "Unconfirmed annotations should be deleted")
        self.assertEqual(
            self.source.image_set.unconfirmed().count(), 0,
            "No images should be classified")


class LabelsetAddRemoveInfoPopupTest(LabelTest):
    """
    Test the label info popup that's available on the Add/Remove Labels page.
    """
    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.labels = cls.create_labels(
            cls.user, ['A', 'B', 'C', 'D', 'E'], "Group1")
        cls.source = cls.create_source(cls.user)
        cls.create_labelset(cls.user, cls.source, cls.labels.filter(
            default_code__in=['A', 'B', 'C']))

    def get_add_remove_labels_page(self):
        self.client.force_login(self.user)
        return self.client.get(reverse('labelset_add', args=[self.source.pk]))

    def test_calcify_info(self):
        # Add calcification rates for A only, not the other labels
        CalcifyRateTable(
            name="Table Name", description="Desc",
            rates_json={
                str(self.labels.get(name='A').pk): dict(
                    mean='2.0', lower_bound='1.0', upper_bound='3.0'),
            },
            source=None).save()

        response = self.get_add_remove_labels_page()
        response_soup = BeautifulSoup(response.content, 'html.parser')

        label_a = self.labels.get(name="A")
        detail_box = response_soup.select(
            f'div.label-detail-box[data-label-id="{label_a.pk}"]')[0]
        self.assertIn(
            "Calcification rate data: Available", str(detail_box),
            "Should say A has rates available")

        label_b = self.labels.get(name="B")
        detail_box = response_soup.select(
            f'div.label-detail-box[data-label-id="{label_b.pk}"]')[0]
        self.assertIn(
            "Calcification rate data: Not available", str(detail_box),
            "Should say B does not have rates available")


class LabelsetEditTest(LabelTest):
    """
    General tests for the view where you edit labelset entries (code etc.).
    """
    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user()

        # Create labels and group
        cls.group = cls.create_label_group("Group1")
        cls.global_labels = dict(
            A=cls.create_label(cls.user, "Label A", 'A', cls.group),
            B=cls.create_label(cls.user, "Label B", 'B', cls.group),
            C=cls.create_label(cls.user, "Label C", 'C', cls.group),
            D=cls.create_label(cls.user, "Label D", 'D', cls.group),
            E=cls.create_label(cls.user, "Label E", 'E', cls.group),
        )

        # Create source and labelset
        cls.source = cls.create_source(cls.user)
        cls.create_labelset(cls.user, cls.source, Label.objects.filter(
            default_code__in=['A', 'B']))

        cls.url = reverse('labelset_edit', args=[cls.source.pk])

    def test_success(self):
        local_labels = self.source.labelset.get_labels()
        post_data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': local_labels.get(
                global_label_id=self.global_labels['A'].pk).pk,
            'form-0-code': 'newCodeA',
            'form-1-id': local_labels.get(
                global_label_id=self.global_labels['B'].pk).pk,
            'form-1-code': 'newCodeB',
        }

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data, follow=True)
        self.assertContains(
            response, "Label entries successfully edited.",
            msg_prefix="Page should show the success message")

        self.source.labelset.refresh_from_db()
        local_labels = self.source.labelset.get_labels()
        label_A = local_labels.get(global_label_id=self.global_labels['A'].pk)
        self.assertEqual(label_A.code, 'newCodeA')
        label_B = local_labels.get(global_label_id=self.global_labels['B'].pk)
        self.assertEqual(label_B.code, 'newCodeB')

    def test_unicode(self):
        """Accept any Unicode characters in custom label codes."""
        local_labels = self.source.labelset.get_labels()
        post_data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': local_labels.get(
                global_label_id=self.global_labels['A'].pk).pk,
            'form-0-code': 'Rödalger',
            'form-1-id': local_labels.get(
                global_label_id=self.global_labels['B'].pk).pk,
            'form-1-code': '紅藻',
        }

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data, follow=True)
        self.assertContains(
            response, "Label entries successfully edited.",
            msg_prefix="Page should show the success message")

        self.source.labelset.refresh_from_db()
        local_labels = self.source.labelset.get_labels()
        label_A = local_labels.get(global_label_id=self.global_labels['A'].pk)
        self.assertEqual(label_A.code, 'Rödalger')
        label_B = local_labels.get(global_label_id=self.global_labels['B'].pk)
        self.assertEqual(label_B.code, '紅藻')

    def test_code_missing(self):
        local_labels = self.source.labelset.get_labels()
        post_data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': local_labels.get(
                global_label_id=self.global_labels['A'].pk).pk,
            'form-0-code': 'newCodeA',
            'form-1-id': local_labels.get(
                global_label_id=self.global_labels['B'].pk).pk,
            'form-1-code': '',
        }

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)

        self.assertContains(
            response,
            "Label B: Short Code: This field is required.")

    def test_code_error(self):
        local_labels = self.source.labelset.get_labels()
        post_data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': local_labels.get(
                global_label_id=self.global_labels['A'].pk).pk,
            'form-0-code': 'newCodeATooLong',
            'form-1-id': local_labels.get(
                global_label_id=self.global_labels['B'].pk).pk,
            'form-1-code': 'newCodeA',
        }

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)

        self.assertContains(
            response,
            "Label A: Short Code: Ensure this value has"
            " at most 10 characters (it has 15).")

    def test_code_conflict(self):
        local_labels = self.source.labelset.get_labels()
        post_data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': local_labels.get(
                global_label_id=self.global_labels['A'].pk).pk,
            'form-0-code': 'newCodeA',
            'form-1-id': local_labels.get(
                global_label_id=self.global_labels['B'].pk).pk,
            'form-1-code': 'NEWCODEA',
        }

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)

        self.assertContains(response, escape(
            "The resulting labelset would have multiple labels with the code"
            " 'newcodea' (non case sensitive). This is not allowed."))

    def test_deny_local_label_ids_of_other_source(self):
        """
        Attempts to submit LocalLabel IDs of another source should be rejected.
        Otherwise there's a security hole.

        Specifically, what happens here is that the edits to the outside-ID
        object are ignored, and no error is returned. This is the expected
        behavior when an ID is outside of the Django formset's queryset.
        """
        source_2 = self.create_source(self.user)
        self.create_labelset(self.user, source_2, Label.objects.filter(
            default_code__in=['A', 'B']))

        s2_local_labels = source_2.labelset.get_labels()
        post_data = {
            'form-TOTAL_FORMS': 2,
            'form-INITIAL_FORMS': 2,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': s2_local_labels.get(
                global_label_id=self.global_labels['A'].pk).pk,
            'form-0-code': 'newCodeA',
            'form-1-id': s2_local_labels.get(
                global_label_id=self.global_labels['B'].pk).pk,
            'form-1-code': 'newCodeB',
        }

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data, follow=True)
        self.assertContains(
            response, "Label entries successfully edited.",
            msg_prefix="Page should show the success message")

        source_2.labelset.refresh_from_db()
        s2_local_labels = source_2.labelset.get_labels()
        label_A = s2_local_labels.get(
            global_label_id=self.global_labels['A'].pk)
        self.assertEqual(label_A.code, 'A', "A's code should be unchanged")
        label_B = s2_local_labels.get(
            global_label_id=self.global_labels['B'].pk)
        self.assertEqual(label_B.code, 'B', "B's code should be unchanged")

    def test_deny_nonexistent_local_label_ids(self):
        """
        Attempts to submit nonexistent LocalLabel IDs should result in
        sane behavior (not a 500 error or something).
        """
        post_data = {
            'form-TOTAL_FORMS': 1,
            'form-INITIAL_FORMS': 1,
            'form-MAX_NUM_FORMS': '',
            'form-0-id': -1,
            'form-0-code': 'newCodeA',
        }

        self.client.force_login(self.user)
        response = self.client.post(self.url, post_data)

        self.assertContains(response, escape(
            "(No name): Id: Select a valid choice."
            " That choice is not one of the available choices."))
