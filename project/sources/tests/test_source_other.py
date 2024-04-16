import html
import math
import re
from unittest import skip

from bs4 import BeautifulSoup
from django.template.defaultfilters import date as date_template_filter
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from images.model_utils import PointGen
from images.models import Source
from jobs.tasks import run_scheduled_jobs_until_empty
from lib.tests.utils import BasePermissionTest, ClientTest
from newsfeed.models import NewsItem
from vision_backend.models import Classifier
from vision_backend.tests.tasks.utils import (
    BaseTaskTest, do_collect_spacer_jobs)
from vision_backend.utils import schedule_source_check


class PermissionTest(BasePermissionTest):
    """
    Test permissions for source-related views other than source about and
    source list, which are tested in different classes. (Those views have
    specific redirect logic.)
    """
    def test_source_detail_box(self):
        url = reverse('source_detail_box', args=[self.source.pk])

        self.source_to_private()
        self.assertPermissionLevel(url, self.SIGNED_OUT, is_json=True)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, is_json=True)

    def test_source_main(self):
        url = reverse('source_main', args=[self.source.pk])
        template = 'sources/source_main.html'

        self.source_to_private()
        self.assertPermissionLevel(url, self.SOURCE_VIEW, template=template)
        self.source_to_public()
        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)


class SourceAboutTest(ClientTest):
    """
    Test the About Sources page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user_with_sources = cls.create_user()
        cls.user_without_sources = cls.create_user()

        cls.private_source = cls.create_source(
            cls.user_with_sources,
            visibility=Source.VisibilityTypes.PRIVATE)
        cls.public_source = cls.create_source(
            cls.user_with_sources,
            visibility=Source.VisibilityTypes.PUBLIC)

    def test_load_page_anonymous(self):
        response = self.client.get(reverse('source_about'))
        self.assertTemplateUsed(response, 'sources/source_about.html')
        self.assertContains(
            response, "You need an account to work with Sources")
        # Source list should just have the public source
        self.assertContains(response, self.public_source.name)
        self.assertNotContains(response, self.private_source.name)

    def test_load_page_without_source_memberships(self):
        self.client.force_login(self.user_without_sources)
        response = self.client.get(reverse('source_about'))
        self.assertTemplateUsed(response, 'sources/source_about.html')
        self.assertContains(
            response, "You're not part of any Sources")
        # Source list should just have the public source
        self.assertContains(response, self.public_source.name)
        self.assertNotContains(response, self.private_source.name)

    def test_load_page_with_source_memberships(self):
        self.client.force_login(self.user_with_sources)
        response = self.client.get(reverse('source_about'))
        self.assertTemplateUsed(response, 'sources/source_about.html')
        self.assertContains(
            response, "See your Sources")
        # Source list should just have the public source
        self.assertContains(response, self.public_source.name)
        self.assertNotContains(response, self.private_source.name)


class SourceListTest(ClientTest):
    """
    Test the source list page (except the map).
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.admin = cls.create_user()

        # Create sources with names to ensure a certain source list order
        cls.private_source = cls.create_source(
            cls.admin, name="Source 1",
            visibility=Source.VisibilityTypes.PRIVATE)
        cls.public_source = cls.create_source(
            cls.admin, name="Source 2",
            visibility=Source.VisibilityTypes.PUBLIC)

    def test_anonymous(self):
        response = self.client.get(reverse('source_list'), follow=True)
        # Should redirect to source_about
        self.assertTemplateUsed(response, 'sources/source_about.html')

    def test_member_of_none(self):
        user = self.create_user()
        self.client.force_login(user)

        response = self.client.get(reverse('source_list'), follow=True)
        # Should redirect to source_about
        self.assertTemplateUsed(response, 'sources/source_about.html')

    def test_member_of_public(self):
        user = self.create_user()
        self.add_source_member(
            self.admin, self.public_source, user, Source.PermTypes.VIEW.code)
        self.client.force_login(user)

        response = self.client.get(reverse('source_list'))
        self.assertTemplateUsed(response, 'sources/source_list.html')
        self.assertListEqual(
            list(response.context['your_sources']),
            [dict(
                id=self.public_source.pk, name=self.public_source.name,
                your_role="View")]
        )
        self.assertListEqual(
            list(response.context['other_public_sources']),
            []
        )

    def test_member_of_private(self):
        user = self.create_user()
        self.add_source_member(
            self.admin, self.private_source, user, Source.PermTypes.VIEW.code)
        self.client.force_login(user)

        response = self.client.get(reverse('source_list'))
        self.assertTemplateUsed(response, 'sources/source_list.html')
        self.assertListEqual(
            list(response.context['your_sources']),
            [
                dict(
                    id=self.private_source.pk, name=self.private_source.name,
                    your_role="View"
                ),
            ]
        )
        self.assertListEqual(
            list(response.context['other_public_sources']),
            [self.public_source]
        )

    def test_member_of_public_and_private(self):
        user = self.create_user()
        self.add_source_member(
            self.admin, self.private_source, user, Source.PermTypes.EDIT.code)
        self.add_source_member(
            self.admin, self.public_source, user, Source.PermTypes.ADMIN.code)
        self.client.force_login(user)

        response = self.client.get(reverse('source_list'))
        self.assertTemplateUsed(response, 'sources/source_list.html')
        # Sources should be in name-alphabetical order
        self.assertListEqual(
            list(response.context['your_sources']),
            [
                dict(
                    id=self.private_source.pk, name=self.private_source.name,
                    your_role="Edit"
                ),
                dict(
                    id=self.public_source.pk, name=self.public_source.name,
                    your_role="Admin"
                ),
            ]
        )
        self.assertListEqual(
            list(response.context['other_public_sources']),
            []
        )


class SourceDetailBoxTest(ClientTest):
    """
    Test the map's source detail popup box.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    def test_private_source(self):
        source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PRIVATE,
            affiliation="My Affiliation",
            description="My Description",
        )
        for _ in range(3):
            self.upload_image(self.user, source)

        response = self.client.get(
            reverse('source_detail_box', args=[source.pk]))
        detail_html = response.json()['detailBoxHtml']

        self.assertIn(source.name, detail_html)
        self.assertNotIn(reverse('source_main', args=[source.pk]), detail_html)

        self.assertIn("My Affiliation", detail_html)
        self.assertIn("My Description", detail_html)
        self.assertIn("Number of images: 3", detail_html)
        self.assertNotIn('class="source-example-image"', detail_html)

    def test_public_source(self):
        source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PUBLIC,
            affiliation="My Affiliation",
            description="My Description",
        )
        for _ in range(3):
            self.upload_image(self.user, source)

        response = self.client.get(
            reverse('source_detail_box', args=[source.pk]))
        detail_html = response.json()['detailBoxHtml']

        self.assertIn(source.name, detail_html)
        self.assertIn(reverse('source_main', args=[source.pk]), detail_html)

        self.assertIn("My Affiliation", detail_html)
        self.assertIn("My Description", detail_html)
        self.assertIn("Number of images: 3", detail_html)
        self.assertIn('class="source-example-image"', detail_html)


class SourceMainTest(ClientTest):
    """
    Test a source's main page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user("user1")

    def test_source_members_box(self):
        source = self.create_source(self.user)

        user_viewer = self.create_user("user2")
        self.add_source_member(
            self.user, source, user_viewer, Source.PermTypes.VIEW.code)
        user_editor = self.create_user("user3")
        self.add_source_member(
            self.user, source, user_editor, Source.PermTypes.EDIT.code)

        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))

        # Should be ordered by role first, not by username first
        self.assertInHTML(
            '<tr><td><a href="{}">{}</a></td><td><b>Admin</b></td></tr>'
            '<tr><td><a href="{}">{}</a></td><td><b>Edit</b></td></tr>'
            '<tr><td><a href="{}">{}</a></td><td><b>View</b></td></tr>'.format(
                reverse('profile_detail', args=[self.user.pk]), "user1",
                reverse('profile_detail', args=[user_editor.pk]), "user3",
                reverse('profile_detail', args=[user_viewer.pk]), "user2",
            ),
            response.content.decode())

    def test_source_fields_box_1_basics(self):
        source = self.create_source(
            self.user,
            min_x=0, max_x=100, min_y=5, max_y=95,
            point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=5,
            confidence_threshold=80,
            feature_extractor_setting='efficientnet_b0_ver1',
            description="This is a\nmultiline description.")

        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))

        self.assertContains(
            response,
            "Default image annotation area: X: 0 - 100% / Y: 5 - 95%")
        self.assertContains(
            response, "Annotation point generation: Simple random, 5 points")
        self.assertContains(
            response, "Feature extractor: EfficientNet (default)")
        self.assertContains(response, "Confidence threshold: 80%")
        self.assertInHTML(
            '<br><br>This is a<br>multiline description.',
            response.content.decode())

    def test_source_fields_box_1_without_robot(self):
        """
        With-robot test is in another class which better
        supports running tasks.
        """
        source = self.create_source(self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))

        self.assertNotContains(response, "Last classifier saved:")
        self.assertNotContains(response, "Last classifier trained:")

    def test_source_fields_box_2(self):
        source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PUBLIC,
            latitude='30.0296', longitude='-15.6402',
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))

        self.assertContains(response, 'Visibility: <b>Public</b>')
        self.assertContains(response, 'Latitude: <b>30.0296</b>')
        self.assertContains(response, 'Longitude: <b>-15.6402</b>')

    def test_latest_images(self):
        source = self.create_source(self.user)

        # Upload 4 images
        self.upload_image(self.user, source)
        img2 = self.upload_image(self.user, source)
        img3 = self.upload_image(self.user, source)
        img4 = self.upload_image(self.user, source)
        # Another image in another source; shouldn't appear on the page
        other_source = self.create_source(self.user)
        self.upload_image(self.user, other_source)

        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))

        response_soup = BeautifulSoup(response.content, 'html.parser')
        images_div = response_soup.find('div', id='images')
        a_elements = images_div.find_all('a')
        href_attributes = [
            element.attrs.get('href') for element in a_elements]

        # Should have the last 3 images from latest to earliest
        self.assertListEqual(
            href_attributes,
            [
                reverse('image_detail', args=[img4.pk]),
                reverse('image_detail', args=[img3.pk]),
                reverse('image_detail', args=[img2.pk]),
            ],
        )

    def test_image_status_box(self):
        source = self.create_source(
            self.user, point_generation_type=PointGen.Types.SIMPLE,
            simple_number_of_points=1)
        labels = self.create_labels(self.user, ['A', 'B'], 'GroupA')
        self.create_labelset(self.user, source, labels)
        robot = self.create_robot(source)

        # Unclassified
        self.upload_image(self.user, source)

        # Unconfirmed
        img = self.upload_image(self.user, source)
        self.add_robot_annotations(robot, img)
        img = self.upload_image(self.user, source)
        self.add_robot_annotations(robot, img)

        # Confirmed
        img = self.upload_image(self.user, source)
        self.add_robot_annotations(robot, img)
        self.add_annotations(self.user, img, {1: 'A'})

        # Another image in another source; shouldn't change the results
        other_source = self.create_source(self.user)
        self.upload_image(self.user, other_source)

        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))
        source_main_content = response.content.decode()

        # Grab the browse URLs from the image status box, and assert that
        # following the URLs works as expected.

        for status_main_page, status_browse_thumb, count in [
                ('Unclassified', 'unclassified', 1),
                ('Unconfirmed', 'unconfirmed', 2),
                ('Confirmed', 'confirmed', 1),
                ('Total images', None, 4)]:

            # Example: `Unconfirmed: <a href="/source/12/browse/images">2</a>`
            status_line_regex = re.compile(r'\s*'.join([
                '{}:'.format(status_main_page),
                r'<a href="([^"]+)">',
                '{}'.format(count),
                r'<\/a>',
            ]))
            self.assertRegex(
                source_main_content, status_line_regex,
                "Line for this status should be present with the correct count")

            match = status_line_regex.search(source_main_content)
            browse_url = match.group(1)
            # &amp; -> &
            browse_url = html.unescape(browse_url)

            response = self.client.get(browse_url)
            response_soup = BeautifulSoup(response.content, 'html.parser')

            thumbnails = response_soup.find_all('img', class_='thumb')
            self.assertEqual(
                len(thumbnails), count,
                msg=(
                    "Following the browse link should show the correct"
                    " number of results"))

            if status_browse_thumb:
                thumbnails = response_soup.find_all(
                    'img', class_=status_browse_thumb)
                self.assertEqual(
                    len(thumbnails), count,
                    msg=(
                        "Following the browse link should show only image"
                        " results of the specified status"))

    @override_settings(TRAINING_MIN_IMAGES=3)
    def test_automated_annotation_section(self):
        source = self.create_source(self.user)

        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))
        self.assertContains(
            response,
            "This source does not have a classifier yet."
            " Need a minimum of 3 Confirmed images to train a classifier.")
        self.assertNotContains(response, '<div id="acc_overview"')

        self.create_robot(source)
        response = self.client.get(reverse('source_main', args=[source.pk]))
        self.assertNotContains(
            response,
            "This source does not have a classifier yet."
            " Need a minimum of 3 Confirmed images to train a classifier.")
        self.assertContains(response, '<div id="acc_overview"')

    @skip("Removed newsfeed box until we're actually using newsitems.")
    def test_newsfeed_box(self):
        source = self.create_source(self.user)
        news_item = NewsItem(
            source_id=source.pk,
            source_name=source.name,
            user_id=self.user.pk,
            user_username=self.user.username,
            message="This is a message",
            category='source',
        )
        news_item.save()

        other_source = self.create_source(self.user)
        other_news_item = NewsItem(
            source_id=other_source.pk,
            source_name=other_source.name,
            user_id=self.user.pk,
            user_username=self.user.username,
            message="This is another message",
            category='source',
        )
        other_news_item.save()

        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))

        self.assertContains(
            response, reverse('newsfeed_details', args=[news_item.pk]))
        self.assertContains(
            response, "This is a message")

        # Don't show news from other sources
        self.assertNotContains(
            response, reverse('newsfeed_details', args=[other_news_item.pk]))


class SourceMainRobotTest(BaseTaskTest):

    @staticmethod
    def date_display(date):
        return date_template_filter(timezone.localtime(date), 'N j, Y, P')

    def test_source_fields_with_robot(self):
        # Train and accept a classifier.
        self.upload_data_and_train_classifier()

        classifier_1 = self.source.classifier_set.latest('pk')
        self.assertEqual(classifier_1.status, Classifier.ACCEPTED)

        # Train and reject a classifier. Override settings so that
        # 1) we don't need more images to train a new classifier, and
        # 2) it's impossible to improve accuracy enough to accept
        # another classifier.
        with override_settings(
                NEW_CLASSIFIER_TRAIN_TH=0.0001,
                NEW_CLASSIFIER_IMPROVEMENT_TH=math.inf):
            # Source was considered all caught up earlier, so need to schedule
            # another check.
            schedule_source_check(self.source.pk)
            # Train
            run_scheduled_jobs_until_empty()
            do_collect_spacer_jobs()

        classifier_2 = self.source.classifier_set.latest('pk')
        self.assertEqual(classifier_2.status, Classifier.REJECTED_ACCURACY)

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('source_main', args=[self.source.pk]))

        save_date = classifier_1.train_job.modify_date
        self.assertContains(
            response,
            f"Last classifier saved: {self.date_display(save_date)}")
        train_date = classifier_2.train_job.modify_date
        self.assertContains(
            response,
            f"Last classifier trained: {self.date_display(train_date)}")

    def test_source_fields_with_robot_without_job(self):
        # Train and accept a classifier.
        self.upload_data_and_train_classifier()

        classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(classifier.status, Classifier.ACCEPTED)

        # Delete the train job associated with the classifier,
        # so that the classifier's create date must be used as
        # a fallback for the train-finish date.
        classifier.train_job.delete()

        self.client.force_login(self.user)
        response = self.client.get(
            reverse('source_main', args=[self.source.pk]))

        date = classifier.create_date
        self.assertContains(
            response,
            f"Last classifier saved: {self.date_display(date)}")
        self.assertContains(
            response,
            f"Last classifier trained: {self.date_display(date)}")
