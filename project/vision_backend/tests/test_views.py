import datetime

from bs4 import BeautifulSoup
from django.urls import reverse
from django.utils import timezone

from export.tests.utils import BaseExportTest
from jobs.models import Job
from jobs.tests.utils import do_job, fabricate_job, JobUtilsMixin
from labels.models import Label
from lib.tests.utils import (
    BasePermissionTest, ClientTest, HtmlAssertionsMixin, scrambled_run)
from .tasks.utils import do_collect_spacer_jobs, source_check_is_scheduled


class PermissionTest(BasePermissionTest):

    def test_backend_main(self):
        url = reverse('backend_main', args=[self.source.pk])
        template = 'vision_backend/backend_main.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)

    def test_backend_overview(self):
        # Requires at least 1 image
        self.upload_image(self.user, self.source)

        url = reverse('backend_overview')
        template = 'vision_backend/overview.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)

    def test_request_source_check(self):
        url = reverse('request_source_check', args=[self.source.pk])
        template = 'jobs/source_job_list.html'

        self.source_to_private()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, template=template, post_data={})
        self.source_to_public()
        self.assertPermissionLevel(
            url, self.SOURCE_EDIT, template=template, post_data={})

    def test_cm_test(self):
        url = reverse('cm_test')
        template = 'vision_backend/cm_test.html'

        self.assertPermissionLevel(
            url, self.SUPERUSER, template=template,
            deny_type=self.REQUIRE_LOGIN)


class BackendMainTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labels(cls.user, ['C'], 'Group2')
        labels = Label.objects.all()
        cls.create_labelset(cls.user, cls.source, labels)
        cls.valres_classes = [
            labels.get(name=name).pk for name in ['A', 'B', 'C']]

        cls.url = reverse('backend_main', args=[cls.source.pk])

    def test_no_robot(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)

        self.assertNotContains(response, '<div id="cm"')
        self.assertContains(
            response, "This source does not have an automated classifier yet.")

    def test_confusion_matrix(self):
        robot = self.create_robot(self.source)
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
            est=[0, 0, 1, 1, 1, 1, 1, 1, 1, 0],
            scores=[.8]*10,
        )

        # Add valres to the session so that we don't have to create it in S3.
        #
        # "Be careful: To modify the session and then save it,
        # it must be stored in a variable first (because a new SessionStore
        # is created every time this property is accessed)"
        # http://stackoverflow.com/a/4454671/
        session = self.client.session
        session['valres'] = valres
        session['classifier_id'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.get(self.url)

        # Confusion matrix element should be on the page
        self.assertContains(response, '<div id="cm"')
        self.assertNotContains(
            response, "This source does not have an automated classifier yet.")

        # Check the confusion matrix context var
        # A: 2 classed as A, 4 classed as B (33% / 67%)
        # B: 1 classed as A, 3 classed as B (25% / 75%)
        # C: 0
        # Total: 10 points, 5 (50%) correctly classed
        context_cm = response.context['cm']
        self.assertListEqual(
            context_cm['data_'],
            [
                [0, 0, 0], [0, 1, 25], [0, 2, 33],
                [1, 0, 0], [1, 1, 75], [1, 2, 67],
                [2, 0, 0], [2, 1,  0], [2, 2,  0],
            ]
        )
        self.assertEqual(
            context_cm['xlabels'],
            '["A (A)", "B (B)", "C (C)"]')
        self.assertEqual(
            context_cm['ylabels'],
            '["C (C) [n:0]", "B (B) [n:4]", "A (A) [n:6]"]')
        self.assertEqual(
            context_cm['title_'],
            '"Confusion matrix for full labelset (acc:50.0, n: 10)"')
        self.assertEqual(context_cm['css_height'], 500)
        self.assertEqual(context_cm['css_width'], 600)

    def test_confusion_matrix_many_labels(self):
        source = self.create_source(self.user)

        # '0', ..., '51'
        label_names = [str(n) for n in range(0, 51+1)]
        labels = self.create_labels(self.user, label_names, 'NumberGroup')
        self.create_labelset(self.user, source, labels)

        robot = self.create_robot(source)
        # Every label twice, except '30' and '31' which appear once.
        # This gives us 50 'most common' labels and 2 labels which will be
        # grouped into 'OTHER'.
        annotations_as_label_indices = list(range(0, 51+1)) * 2
        annotations_as_label_indices.remove(30)
        annotations_as_label_indices.remove(31)
        valres = dict(
            classes=[labels.get(name=name).pk for name in label_names],
            gt=annotations_as_label_indices,
            est=annotations_as_label_indices,
            scores=[.8]*102,
        )

        session = self.client.session
        session['valres'] = valres
        session['classifier_id'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.get(reverse('backend_main', args=[source.pk]))

        context_cm = response.context['cm']

        # Cut from 52 labels to 50 labels + 1 'OTHER' label
        self.assertEqual(len(context_cm['data_']), 51*51)

        self.assertIn('0 (0)', context_cm['xlabels'])
        self.assertIn('51 (51)', context_cm['xlabels'])
        self.assertIn('OTHER', context_cm['xlabels'])
        self.assertNotIn('30 (30)', context_cm['xlabels'])
        self.assertNotIn('31 (31)', context_cm['xlabels'])

        self.assertIn('0 (0)', context_cm['ylabels'])
        self.assertIn('51 (51)', context_cm['ylabels'])
        self.assertIn('OTHER', context_cm['ylabels'])
        self.assertNotIn('30 (30)', context_cm['ylabels'])
        self.assertNotIn('31 (31)', context_cm['ylabels'])

    def test_confidence_threshold_non_integer(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url, data=dict(
            confidence_threshold='abc',
            label_mode='full',
        ))

        self.assertStatusOK(
            response,
            "Should at least not get a server error")

    def test_label_mode_invalid(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url, data=dict(
            confidence_threshold='0',
            label_mode='unrecognized_mode',
        ))

        self.assertStatusOK(
            response,
            "Should at least not get a server error")


class BackendMainConfusionMatrixExportTest(BaseExportTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.source = cls.create_source(cls.user)
        cls.create_labels(cls.user, ['A', 'B'], 'Group1')
        cls.create_labels(cls.user, ['C'], 'Group2')
        labels = Label.objects.all()
        cls.create_labelset(cls.user, cls.source, labels)
        cls.valres_classes = [
            labels.get(name=name).pk for name in ['A', 'B', 'C']]

        cls.url = reverse('backend_main', args=[cls.source.pk])

    def test_export_basic(self):
        robot = self.create_robot(self.source)
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
            est=[0, 0, 1, 1, 1, 1, 1, 1, 1, 0],
            scores=[.8]*10,
        )

        # Add valres to the session so that we don't have to create it in S3.
        session = self.client.session
        session['valres'] = valres
        session['classifier_id'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.post(
            self.url, data=dict(export_cm="Export confusion matrix"))

        expected_lines = [
            'A (A),2,4,0',
            'B (B),1,3,0',
            'C (C),0,0,0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_export_with_confidence_threshold(self):
        robot = self.create_robot(self.source)
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
            est=[0, 0, 1, 1, 1, 1, 1, 1, 1, 0],
            scores=[.9, .9, .9, .8, .8, .8, .8, .7, .7, .7],
        )
        session = self.client.session
        session['valres'] = valres
        session['classifier_id'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.post(
            self.url + '?label_mode=full&confidence_threshold=75',
            data=dict(export_cm="Export confusion matrix"))

        expected_lines = [
            'A (A),2,4,0',
            'B (B),0,1,0',
            'C (C),0,0,0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_export_in_functional_groups_mode(self):
        robot = self.create_robot(self.source)

        # 0 and 1 are in Group1; 2 is in Group2. Being in functional groups
        # mode means we don't care if gt/est are 0/0, 0/1, 1/0, or 1/1. Those
        # are all matches for Group1.
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 1, 1, 1, 2, 2, 2, 2],
            est=[0, 1, 2, 0, 1, 2, 0, 1, 1, 2],
            scores=[.8]*10,
        )
        session = self.client.session
        session['valres'] = valres
        session['classifier_id'] = robot.pk
        session.save()

        self.client.force_login(self.user)
        response = self.client.post(
            self.url + '?label_mode=func&confidence_threshold=0',
            data=dict(export_cm="Export confusion matrix"))

        expected_lines = [
            'Group1,4,2',
            'Group2,3,1',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)

    def test_export_with_unicode(self):
        robot = self.create_robot(self.source)
        valres = dict(
            classes=self.valres_classes,
            gt=[0, 0, 0, 0, 0, 0, 1, 1, 1, 1],
            est=[0, 0, 1, 1, 1, 1, 1, 1, 1, 0],
            scores=[.8]*10,
        )
        session = self.client.session
        session['valres'] = valres
        session['classifier_id'] = robot.pk
        session.save()

        local_label_a = self.source.labelset.get_labels().get(code='A')
        local_label_a.code = 'あ'
        local_label_a.save()

        self.client.force_login(self.user)
        response = self.client.post(
            self.url, data=dict(export_cm="Export confusion matrix"))

        expected_lines = [
            'A (あ),2,4,0',
            'B (B),1,3,0',
            'C (C),0,0,0',
        ]
        self.assert_csv_content_equal(response.content, expected_lines)


class RequestSourceCheckTest(ClientTest, HtmlAssertionsMixin, JobUtilsMixin):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    def submit(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('request_source_check', args=[self.source.pk]),
            follow=True)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        return response_soup

    def test_scheduled_after_no_recent_check(self):
        self.assertFalse(source_check_is_scheduled(self.source.pk))

        response_soup = self.submit()
        self.assert_top_message(response_soup, "Source check scheduled.")
        self.assertTrue(source_check_is_scheduled(self.source.pk))

        job = self.get_latest_job_by_name('check_source')
        self.assertAlmostEqual(
            job.scheduled_start_date, timezone.now(),
            delta=datetime.timedelta(minutes=2),
            msg="Scheduled date should be close to now",
        )

    def test_scheduled_after_recent_check(self):
        # Last check was 20 minutes ago
        fabricate_job(
            'check_source', status=Job.Status.SUCCESS,
            source_id=self.source.pk,
            modify_date=timezone.now() - datetime.timedelta(hours=2))
        fabricate_job(
            'check_source', status=Job.Status.SUCCESS,
            source_id=self.source.pk,
            modify_date=timezone.now() - datetime.timedelta(minutes=20))

        response_soup = self.submit()
        self.assert_top_message(response_soup, "Source check scheduled.")

        # Base delay is 30m, last was 20m ago, so delay by 30 - 20 = 10m
        job = self.get_latest_job_by_name('check_source')
        self.assertAlmostEqual(
            job.scheduled_start_date,
            timezone.now() + datetime.timedelta(minutes=10),
            delta=datetime.timedelta(minutes=2),
            msg="Scheduled date should be close to 10 minutes from now",
        )

    def test_scheduled_immediately_after_recent_check(self):
        # Last check was just now
        fabricate_job(
            'check_source', status=Job.Status.SUCCESS,
            source_id=self.source.pk)

        response_soup = self.submit()
        self.assert_top_message(response_soup, "Source check scheduled.")

        # Full base delay of 30m
        job = self.get_latest_job_by_name('check_source')
        self.assertAlmostEqual(
            job.scheduled_start_date,
            timezone.now() + datetime.timedelta(minutes=30),
            delta=datetime.timedelta(minutes=2),
            msg="Scheduled date should be close to 30 minutes from now",
        )

    def test_doing_source_job(self):
        # Pending
        job = fabricate_job(
            'train_classifier', status=Job.Status.PENDING,
            source_id=self.source.pk)
        self.assert_top_message(
            self.submit(), "There are still active jobs to wait for.")
        self.assertFalse(source_check_is_scheduled(self.source.pk))

        # In progress
        job.status = Job.Status.IN_PROGRESS
        job.save()
        self.assert_top_message(
            self.submit(), "There are still active jobs to wait for.")
        self.assertFalse(source_check_is_scheduled(self.source.pk))

        # Reset job, not just 'core' VB job
        job.job_name = 'reset_classifiers_for_source'
        job.save()
        self.assert_top_message(
            self.submit(), "There are still active jobs to wait for.")
        self.assertFalse(source_check_is_scheduled(self.source.pk))

    def test_doing_other_source_job(self):
        """Shouldn't matter that a different source is running a job."""
        source_2 = self.create_source(self.user)
        fabricate_job(
            'train_classifier', status=Job.Status.PENDING,
            source_id=source_2.pk)
        self.assert_top_message(self.submit(), "Source check scheduled.")
        self.assertTrue(source_check_is_scheduled(self.source.pk))


class BackendOverviewTest(ClientTest, HtmlAssertionsMixin):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.labels = cls.create_labels(cls.user, ['A', 'B'], "Group1")

        cls.url = reverse('backend_overview')

    def test(self):
        """
        This test is somewhat haphazard and definitely doesn't test all
        cases/values.
        """
        source1 = self.create_source(self.user)
        source2 = self.create_source(self.user)
        self.create_labelset(self.user, source1, self.labels)
        self.create_labelset(self.user, source2, self.labels)

        image1a = self.upload_image(self.user, source1)
        image1b = self.upload_image(self.user, source1)
        image1c = self.upload_image(self.user, source1)
        _image1d = self.upload_image(self.user, source1)
        self.add_annotations(self.user, image1a)
        self.add_annotations(self.user, image1b)
        do_job('extract_features', image1c.pk, source_id=source1.pk)
        do_collect_spacer_jobs()

        classifier2 = self.create_robot(source2)
        image2a = self.upload_image(self.user, source2)
        image2b = self.upload_image(self.user, source2)
        image2c = self.upload_image(self.user, source2)
        image2d = self.upload_image(self.user, source2)
        _image2e = self.upload_image(self.user, source2)
        self.add_annotations(self.user, image2a)
        self.add_robot_annotations(classifier2, image2b)
        self.add_robot_annotations(classifier2, image2c)
        do_job('extract_features', image2d.pk, source_id=source2.pk)
        do_collect_spacer_jobs()

        self.client.force_login(self.superuser)
        response = self.client.get(self.url)
        response_soup = BeautifulSoup(response.content, 'html.parser')

        image_counts_table_soup = response_soup.select(
            'table#image-counts-table')[0]
        self.assert_table_values(image_counts_table_soup, [
            # 1a, 1b, 2a
            ["Confirmed", "3", "33.3%"],
            # 2b, 2c
            ["Unconfirmed", "2", "22.2%"],
            # 1d, 2e
            ["Unclassified, need features", "2", "22.2%"],
            # 2d
            ["Unclassified, need classification", "1", "11.1%"],
            # 1c
            ["Unclassified, not ready for features/classification",
             "1", "11.1%"],
            ["All", "9", "100.0%"],
        ])

        sources_table_soup = response_soup.select(
            'table#sources-table')[0]
        self.assert_table_values(sources_table_soup, [
            {
                "ID": (
                    f'<a href="'
                    f'{reverse("source_main", args=[source2.pk])}">'
                    f'{source2.pk}'
                    f'</a>'
                ),
                "# Imgs": 5,
                "# Conf.": 1,
            },
            {
                "ID": (
                    f'<a href="'
                    f'{reverse("source_main", args=[source1.pk])}">'
                    f'{source1.pk}'
                    f'</a>'
                ),
                "# Imgs": 4,
                "# Conf.": 2,
            },
        ])

    def test_source_order(self):
        def f1(_num):
            source_ = self.create_source(self.user)
            self.upload_image(self.user, source_)
            # This check will confirm there is stuff to do (extract features).
            # Being the only such source, this should be ordered first in
            # the view.
            do_job('check_source', source_.pk, source_id=source_.pk)
            return source_

        def f2(_num):
            source_ = self.create_source(self.user)
            # This check will confirm there is nothing to do. Ordered second.
            do_job('check_source', source_.pk, source_id=source_.pk)
            return source_

        def f3(_num):
            return self.create_source(self.user)
            # No check. Ordered third.

        run_order, returned_sources = scrambled_run([f1, f2, f3])

        expected_rows = []
        for run_number in run_order:
            source = returned_sources[run_number]
            expected_rows.append({"ID": (
                f'<a href="'
                f'{reverse("source_main", args=[source.pk])}">'
                f'{source.pk}'
                f'</a>'
            )})

        self.client.force_login(self.superuser)
        response = self.client.get(self.url)
        response_soup = BeautifulSoup(response.content, 'html.parser')
        sources_table_soup = response_soup.select(
            'table#sources-table')[0]
        self.assert_table_values(sources_table_soup, expected_rows)
