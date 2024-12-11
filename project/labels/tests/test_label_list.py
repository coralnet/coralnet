from bs4 import BeautifulSoup
from django.contrib.auth.models import Group
from django.urls import reverse

from calcification.tests.utils import create_global_calcify_table
from jobs.tests.utils import do_job
from lib.tests.utils import BasePermissionTest, ClientTest
from ..models import LabelGroup, Label


class PermissionTest(BasePermissionTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.labels = cls.create_labels(cls.user, ['A', 'B'], 'GroupA')

    def test_label_list(self):
        url = reverse('label_list')
        template = 'labels/label_list.html'

        self.assertPermissionLevel(url, self.SIGNED_OUT, template=template)

    def test_label_list_search_ajax(self):
        url = reverse('label_list_search_ajax')

        self.assertPermissionLevel(url, self.SIGNED_OUT, is_json=True)


class LabelListTest(ClientTest):
    """
    Test the label list page.
    """
    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user()

        cls.user_committee_member = cls.create_user()
        cls.user_committee_member.groups.add(
            Group.objects.get(name="Labelset Committee"))

        # Create labels
        cls.labels = cls.create_labels(
            cls.user, ['A', 'B', 'C'], "Group1")

    def test_load_page(self):
        response = self.client.get(reverse('label_list'))
        self.assertStatusOK(response)

    def test_new_label_link_not_shown_for_regular_user(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('label_list'))
        self.assertNotContains(response, "Create a new label")

    def test_new_label_link_shown_for_committee_member(self):
        self.client.force_login(self.user_committee_member)
        response = self.client.get(reverse('label_list'))
        self.assertContains(response, "Create a new label")

    def test_duplicate_verified_status_indicators(self):
        """
        Test the possible 'endorsement status' levels: verified, duplicate,
        neither.
        """
        label_a = self.labels.get(name='A')
        label_a.verified = True
        label_a.save()

        label_b = self.labels.get(name='B')
        label_b.duplicate = label_a
        label_b.save()

        label_c = self.labels.get(name='C')

        self.client.force_login(self.user)
        response = self.client.get(reverse('label_list'))
        response_soup = BeautifulSoup(response.content, 'html.parser')

        label_a_row_tag = response_soup.select(
            f'tr[data-label-id="{label_a.pk}"]')[0]
        status_cell_tag = label_a_row_tag.select('td.status-cell')[0]
        self.assertIn('alt="Verified"', str(status_cell_tag))
        self.assertNotIn('alt="Duplicate"', str(status_cell_tag))

        label_b_row_tag = response_soup.select(
            f'tr[data-label-id="{label_b.pk}"]')[0]
        status_cell_tag = label_b_row_tag.select('td.status-cell')[0]
        self.assertNotIn('alt="Verified"', str(status_cell_tag))
        self.assertIn('alt="Duplicate"', str(status_cell_tag))

        label_c_row_tag = response_soup.select(
            f'tr[data-label-id="{label_c.pk}"]')[0]
        status_cell_tag = label_c_row_tag.select('td.status-cell')[0]
        self.assertNotIn('alt="Verified"', str(status_cell_tag))
        self.assertNotIn('alt="Duplicate"', str(status_cell_tag))

    def test_calcify_data_indicators(self):
        """
        Test the calcification rate status icon. 1 label with no data,
        1 label with data for some regions, 1 label with data for all regions.
        """
        # A = none (no icon), B = some (icon), C = all (icon)
        label_a = self.labels.get(name='A')
        label_b = self.labels.get(name='B')
        label_c = self.labels.get(name='C')

        # Old Atlantic table; shouldn't be considered at all despite having
        # an entry that's not in the current Atlantic table
        create_global_calcify_table(
            'Atlantic', {
                label_a.pk: dict(mean=5, lower_bound=4, upper_bound=6),
                label_c.pk: dict(mean=2, lower_bound=1, upper_bound=3)})
        # Current Atlantic table
        create_global_calcify_table(
            'Atlantic', {
                label_c.pk: dict(mean=2, lower_bound=1, upper_bound=3)})
        # Current Indo-Pacific table
        create_global_calcify_table(
            'Indo-Pacific', {
                label_b.pk: dict(mean=5, lower_bound=4, upper_bound=6),
                label_c.pk: dict(mean=2, lower_bound=1, upper_bound=3)})

        self.client.force_login(self.user)
        response = self.client.get(reverse('label_list'))
        response_soup = BeautifulSoup(response.content, 'html.parser')

        label_a_row_tag = response_soup.select(
            f'tr[data-label-id="{label_a.pk}"]')[0]
        status_cell_tag = label_a_row_tag.select('td.status-cell')[0]
        self.assertNotIn(
            'alt="Has calcification rate data"', str(status_cell_tag))

        label_b_row_tag = response_soup.select(
            f'tr[data-label-id="{label_b.pk}"]')[0]
        status_cell_tag = label_b_row_tag.select('td.status-cell')[0]
        self.assertIn(
            'alt="Has calcification rate data"', str(status_cell_tag))

        label_c_row_tag = response_soup.select(
            f'tr[data-label-id="{label_c.pk}"]')[0]
        status_cell_tag = label_c_row_tag.select('td.status-cell')[0]
        self.assertIn(
            'alt="Has calcification rate data"', str(status_cell_tag))


class BaseLabelSearchTest(ClientTest):

    def assertLabels(self, response, label_names):
        response_pk_set = set(response.json()['label_ids'])
        expected_pk_set = set(Label.objects.filter(
            name__in=label_names).values_list('pk', flat=True))
        self.assertSetEqual(response_pk_set, expected_pk_set)

    def submit_search(self, **kwargs):
        data = dict(
            name_search='',
            show_verified=True,
            show_regular=True,
            show_duplicate=False,
            functional_group='',
            min_popularity='',
        )
        data.update(kwargs)
        response = self.client.get(self.url, data)
        return response


class LabelSearchNameFieldTest(BaseLabelSearchTest):
    """
    Test the name field of the Ajax label search.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.url = reverse('label_list_search_ajax')

    def test_match_full_name(self):
        self.create_labels(self.user, ["Red", "Blue"], "Group1")

        response = self.submit_search(name_search="Red")
        self.assertLabels(response, ["Red"])

    def test_match_part_of_name(self):
        self.create_labels(self.user, ["Red", "Blue"], "Group1")

        response = self.submit_search(name_search="Blu")
        self.assertLabels(response, ["Blue"])

    def test_match_case_insensitive(self):
        self.create_labels(self.user, ["Red", "Blue"], "Group1")

        response = self.submit_search(name_search="BLUE")
        self.assertLabels(response, ["Blue"])

    def test_match_multiple_labels(self):
        self.create_labels(
            self.user, ["Red", "Light Blue", "Dark Blue"], "Group1")

        response = self.submit_search(name_search="Blue")
        self.assertLabels(response, ["Light Blue", "Dark Blue"])

    def test_multiple_words(self):
        self.create_labels(
            self.user, ["Light Blue", "Dark Blue", "Dark Red"], "Group1")

        response = self.submit_search(name_search="Dark Blue")
        self.assertLabels(response, ["Dark Blue"])

    def test_no_match(self):
        self.create_labels(self.user, ["Red", "Blue"], "Group1")

        response = self.submit_search(name_search="Green")
        self.assertLabels(response, [])

    def test_strip_whitespace(self):
        self.create_labels(self.user, ["Blue", "Red"], "Group1")

        response = self.submit_search(name_search="  Blue ")
        self.assertLabels(response, ["Blue"])

    def test_normalize_multiple_spaces(self):
        self.create_labels(
            self.user, ["Light Blue", "Dark Blue", "Dark Red"], "Group1")

        response = self.submit_search(name_search="Dark   Blue")
        self.assertLabels(response, ["Dark Blue"])

    def test_treat_punctuation_as_spaces(self):
        self.create_labels(
            self.user, ["Light Blue", "Dark Blue", "Dark Red"], "Group1")

        response = self.submit_search(name_search=";'Dark_/Blue=-")
        self.assertLabels(response, ["Dark Blue"])

    def test_no_tokens(self):
        self.create_labels(
            self.user, ["Light Blue", "Dark Blue", "Dark Red"], "Group1")

        response = self.submit_search(name_search=";'_/=-")
        self.assertLabels(response, [])


class LabelSearchOtherFieldsTest(BaseLabelSearchTest):
    """Test fields other than name."""
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.url = reverse('label_list_search_ajax')

        cls.create_labels(cls.user, ['A', 'B'], "Group1")
        cls.create_labels(cls.user, ['C', 'D'], "Group2")

    def test_show_by_status(self):
        label_a = Label.objects.get(name='A')
        label_a.verified = True
        label_a.save()
        label_b = Label.objects.get(name='B')
        label_b.duplicate = label_a
        label_b.save()

        response = self.submit_search(
            show_verified=False, show_regular=False, show_duplicate=False)
        self.assertLabels(response, [])

        response = self.submit_search(
            show_verified=True, show_regular=False, show_duplicate=False)
        self.assertLabels(response, ['A'])

        response = self.submit_search(
            show_verified=False, show_regular=True, show_duplicate=False)
        self.assertLabels(response, ['C', 'D'])

        response = self.submit_search(
            show_verified=False, show_regular=False, show_duplicate=True)
        self.assertLabels(response, ['B'])

        response = self.submit_search(
            show_verified=True, show_regular=True, show_duplicate=False)
        self.assertLabels(response, ['A', 'C', 'D'])

        response = self.submit_search(
            show_verified=True, show_regular=True, show_duplicate=True)
        self.assertLabels(response, ['A', 'B', 'C', 'D'])

    def test_show_by_functional_group(self):
        response = self.submit_search()
        self.assertLabels(response, ['A', 'B', 'C', 'D'])

        response = self.submit_search(
            functional_group=LabelGroup.objects.get(name='Group1').pk)
        self.assertLabels(response, ['A', 'B'])

        response = self.submit_search(
            functional_group=LabelGroup.objects.get(name='Group2').pk)
        self.assertLabels(response, ['C', 'D'])

    def test_show_by_popularity(self):
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(type='simple', points=4))
        self.create_labelset(self.user, source, Label.objects.all())
        img = self.upload_image(self.user, source)
        self.add_annotations(
            self.user, img, {1: 'A', 2: 'A', 3: 'C', 4: 'C'})
        do_job('update_label_details')

        response = self.submit_search()
        self.assertLabels(response, ['A', 'B', 'C', 'D'])

        response = self.submit_search(min_popularity=1)
        self.assertLabels(response, ['A', 'C'])

    def test_multiple_filters(self):
        label_a = Label.objects.get(name='A')
        label_b = Label.objects.get(name='B')
        label_c = Label.objects.get(name='C')

        # A, B, and C are verified
        label_a.verified = True
        label_a.save()
        label_b.verified = True
        label_b.save()
        label_c.verified = True
        label_c.save()

        # A and B are already in Group1

        # A and C have popularity
        source = self.create_source(
            self.user,
            default_point_generation_method=dict(type='simple', points=4))
        self.create_labelset(self.user, source, Label.objects.all())
        img = self.upload_image(self.user, source)
        self.add_annotations(
            self.user, img, {1: 'A', 2: 'A', 3: 'C', 4: 'C'})
        do_job('update_label_details')

        # Only A satisfies all requirements here
        response = self.submit_search(
            show_verified=True, show_regular=False,
            functional_group=LabelGroup.objects.get(name='Group1').pk,
            min_popularity=1)
        self.assertLabels(response, ['A'])


class PerformanceTest(ClientTest):
    """
    Test performance of the label list related views.
    """
    @classmethod
    def setUpTestData(cls):
        # Call the parent's setup (while still using this class as cls)
        super().setUpTestData()

        cls.user = cls.create_user()

        # Create 20 labels
        cls.labels = cls.create_labels(
            cls.user, [str(i) for i in range(20)], "Group1")

    def test_list_num_queries(self):
        # First allow label popularities to be cached.
        self.client.get(reverse('label_list'))

        # Number of queries should be less than the label count.
        with self.assert_queries_less_than(20):
            response = self.client.get(reverse('label_list'))
        self.assertStatusOK(response)

    def test_search_ajax_num_queries(self):
        url = reverse('label_list_search_ajax')
        data = dict(
            name_search='',
            show_verified=True,
            show_regular=True,
            show_duplicate=False,
            functional_group='',
            min_popularity='',
        )

        # Number of queries should be less than the label count.
        with self.assert_queries_less_than(20):
            response = self.client.get(url, data)
        self.assertStatusOK(response)
