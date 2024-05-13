import html
import math
import re
from unittest import skip

from bs4 import BeautifulSoup
from django.test import override_settings
from django.urls import reverse

from jobs.tasks import run_scheduled_jobs_until_empty
from lib.tests.utils import (
    BasePermissionTest, ClientTest, HtmlAssertionsMixin)
from lib.utils import date_display, datetime_display
from newsfeed.models import NewsItem
from vision_backend.models import Classifier
from vision_backend.tests.tasks.utils import (
    BaseTaskTest, do_collect_spacer_jobs)
from vision_backend.utils import schedule_source_check
from ..models import Source


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


class SourceMainTest(ClientTest, HtmlAssertionsMixin):
    """
    Test a source's main page.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user("user1")

    def source_main_soup(self, source):
        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))
        return BeautifulSoup(response.content, 'html.parser')

    def test_description(self):
        source = self.create_source(
            self.user,
            description="This is a\nmultiline description.")
        soup = self.source_main_soup(source)
        # assertInHTML() can't pick up just a subset of child nodes, which
        # is what we're testing for here, so we use assertIn() and make
        # sure to get it right char-for-char.
        self.assertIn(
            'This is a<br/>multiline description.',
            str(soup.find(id='description-box')))

    def test_members_box(self):
        source = self.create_source(
            self.user,
            affiliation="Unit Test Institute")

        user_viewer = self.create_user("user2")
        self.add_source_member(
            self.user, source, user_viewer, Source.PermTypes.VIEW.code)
        user_editor = self.create_user("user3")
        self.add_source_member(
            self.user, source, user_editor, Source.PermTypes.EDIT.code)

        soup = self.source_main_soup(source)
        members_column_soup = soup.find(id='members-column')

        self.assertInHTML(
            "Unit Test Institute", str(members_column_soup))

        def profile_url(user):
            return reverse('profile_detail', args=[user.pk])

        # Should be ordered by role first, not by username first
        self.assert_table_values(
            members_column_soup.find('table'),
            [
                [f'<a href="{profile_url(self.user)}">user1</a>',
                 '<strong>Admin</strong>'],
                [f'<a href="{profile_url(user_editor)}">user3</a>',
                 '<strong>Edit</strong>'],
                [f'<a href="{profile_url(user_viewer)}">user2</a>',
                 '<strong>View</strong>'],
            ])

    def test_details_box(self):
        source = self.create_source(
            self.user,
            visibility=Source.VisibilityTypes.PUBLIC,
            image_annotation_area=dict(min_x=0, max_x=100, min_y=5, max_y=95),
            default_point_generation_method=dict(type='simple', points=5),
            latitude='30.0296', longitude='-15.6402',
        )

        soup = self.source_main_soup(source)
        right_column_soup = soup.find(id='right-column')

        def detail_html(key, value):
            return f'<li><span>{key}:</span><span>{value}</span></li>'

        self.assertInHTML(
            detail_html(
                "Visibility",
                "Public"),
            str(right_column_soup))
        self.assertInHTML(
            detail_html(
                "Default image annotation area",
                "X: 0 - 100% / Y: 5 - 95%"),
            str(right_column_soup))
        self.assertInHTML(
            detail_html(
                "Point generation method",
                "Simple random, 5 points"),
            str(right_column_soup))
        self.assertInHTML(
            detail_html(
                "Latitude & Longitude",
                "30.0296, -15.6402"),
            str(right_column_soup))
        self.assertInHTML(
            detail_html(
                "Created",
                date_display(source.create_date)),
            str(right_column_soup))

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
            self.user,
            default_point_generation_method=dict(type='simple', points=1))
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


class SourceMainBackendColumnTest(BaseTaskTest):

    def source_main_soup(self, source):
        self.client.force_login(self.user)
        response = self.client.get(reverse('source_main', args=[source.pk]))
        return BeautifulSoup(response.content, 'html.parser')

    def assert_detail(self, soup, detail):
        self.assertInHTML(f'<li>{detail}</li>', str(soup))

    acc_overview_id = 'acc-overview'

    @override_settings(TRAINING_MIN_IMAGES=3)
    def test_has_own_classifiers(self):
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

        soup = self.source_main_soup(self.source)
        backend_soup = soup.find(id='backend-column')

        self.assertIsNotNone(backend_soup.find(id=self.acc_overview_id))
        save_date = classifier_1.train_job.modify_date
        self.assert_detail(
            backend_soup,
            f"Last classifier saved: {datetime_display(save_date)}")
        train_date = classifier_2.train_job.modify_date
        self.assert_detail(
            backend_soup,
            f"Last classifier trained: {datetime_display(train_date)}")
        self.assert_detail(
            backend_soup,
            "Feature extractor: EfficientNet (default)")
        self.assert_detail(
            backend_soup,
            "Confidence threshold: 100%")

    @override_settings(TRAINING_MIN_IMAGES=3)
    def test_has_own_classifiers_but_no_job(self):
        """
        A mainly-legacy case where a trained classifier exists, but no
        corresponding training Job exists, thus necessitating getting the
        train date a different (less accurate) way.
        """
        # Train and accept a classifier.
        self.upload_data_and_train_classifier()

        classifier = self.source.classifier_set.latest('pk')
        self.assertEqual(classifier.status, Classifier.ACCEPTED)

        # Delete the train job associated with the classifier,
        # so that the classifier's create date must be used as
        # a fallback for the train-finish date.
        classifier.train_job.delete()

        soup = self.source_main_soup(self.source)
        backend_soup = soup.find(id='backend-column')

        date = classifier.create_date
        self.assert_detail(
            backend_soup,
            f"Last classifier saved: {datetime_display(date)}")
        self.assert_detail(
            backend_soup,
            f"Last classifier trained: {datetime_display(date)}")

    @override_settings(TRAINING_MIN_IMAGES=3)
    def test_has_not_trained_classifier_yet(self):
        source = self.create_source(
            self.user,
            trains_own_classifiers=True,
            feature_extractor_setting='vgg16_coralnet_ver1',
        )

        soup = self.source_main_soup(source)
        backend_soup = soup.find(id='backend-column')

        self.assertIsNone(backend_soup.find(id=self.acc_overview_id))
        self.assert_detail(
            backend_soup,
            "Classifier status: No classifier yet."
            " Need a minimum of 3 Confirmed images to train a classifier.")
        self.assert_detail(
            backend_soup,
            "Feature extractor: VGG16 (legacy)")

    def test_deployed_classifier(self):
        train_source = self.create_source(self.user)
        self.create_labelset(
            self.user, train_source, self.labels.filter(name__in=['A', 'B']))
        classifier = self.create_robot(train_source)

        source = self.create_source(
            self.user,
            trains_own_classifiers=False,
            deployed_classifier=classifier.pk,
        )

        soup = self.source_main_soup(source)
        backend_soup = soup.find(id='backend-column')

        self.assertIsNone(backend_soup.find(id=self.acc_overview_id))
        self.assert_detail(
            backend_soup,
            f"Classifier ID in use: {classifier.pk}")
        train_source_url = reverse('source_main', args=[train_source.pk])
        self.assert_detail(
            backend_soup,
            f"""Classifier's source: <a href="{train_source_url}">"""
            f"""{train_source.name}</a>""")
        self.assert_detail(
            backend_soup,
            "Confidence threshold: 100%")

    def test_deployed_source_id(self):
        train_source = self.create_source(self.user)
        self.create_labelset(
            self.user, train_source, self.labels.filter(name__in=['A', 'B']))
        classifier = self.create_robot(train_source)

        source = self.create_source(
            self.user,
            trains_own_classifiers=False,
            deployed_classifier=classifier.pk,
        )
        classifier.delete()

        soup = self.source_main_soup(source)
        backend_soup = soup.find(id='backend-column')

        self.assertIsNone(backend_soup.find(id=self.acc_overview_id))
        self.assert_detail(
            backend_soup,
            f"Classifier ID in use: None. Previously used a classifier"
            f" from source {train_source.pk}.")

    def test_deployed_none(self):
        source = self.create_source(
            self.user,
            trains_own_classifiers=False,
            deployed_classifier='',
        )

        soup = self.source_main_soup(source)
        backend_soup = soup.find(id='backend-column')

        self.assertIsNone(backend_soup.find(id=self.acc_overview_id))
        self.assert_detail(
            backend_soup,
            "Classifier ID in use: None")
