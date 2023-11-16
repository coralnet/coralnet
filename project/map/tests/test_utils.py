from django.test import override_settings
from django.urls import reverse

from images.models import Source
from jobs.models import Job
from jobs.tests.utils import do_job
from lib.tests.utils import ClientTest
from ..utils import cacheable_map_sources


@override_settings(MAP_IMAGE_COUNT_TIERS=[2, 3, 5])
class MapSourcesTest(ClientTest):
    """
    Test the utility function which gets sources for the map.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()

    def test_all_fields(self):
        source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PUBLIC)
        for _ in range(2):
            self.upload_image(self.user, source)

        self.assertDictEqual(
            cacheable_map_sources.get()[0],
            dict(
                sourceId=source.id,
                latitude=source.latitude,
                longitude=source.longitude,
                type='public',
                size=1,
                detailBoxUrl=reverse('source_detail_box', args=[source.pk]),
            ),
        )

    def test_type_field(self):
        # Test both possible type values.
        public_source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PUBLIC)
        for _ in range(2):
            self.upload_image(self.user, public_source)

        private_source = self.create_source(
            self.user, visibility=Source.VisibilityTypes.PRIVATE)
        for _ in range(2):
            self.upload_image(self.user, private_source)

        # Set comparison, since source order is not defined here.
        ids_and_types = {
            (d['sourceId'], d['type'])
            for d in cacheable_map_sources.get()
        }
        self.assertSetEqual(
            ids_and_types,
            {
                (public_source.pk, 'public'),
                (private_source.pk, 'private'),
            },
        )

    def test_size_field(self):
        """Test all possible source size tiers (size meaning image count)."""
        source_tier_0 = self.create_source(self.user)
        self.upload_image(self.user, source_tier_0)

        source_tier_1 = self.create_source(self.user)
        for _ in range(2):
            self.upload_image(self.user, source_tier_1)

        source_tier_2 = self.create_source(self.user)
        for _ in range(4):
            self.upload_image(self.user, source_tier_2)

        source_tier_3 = self.create_source(self.user)
        for _ in range(5):
            self.upload_image(self.user, source_tier_3)

        # Set comparison, since source order is not defined here.
        # Note that source_tier_0 is not in the map sources.
        ids_and_sizes = {
            (d['sourceId'], d['size'])
            for d in cacheable_map_sources.get()
        }
        self.assertSetEqual(
            ids_and_sizes,
            {
                (source_tier_1.pk, 1),
                (source_tier_2.pk, 2),
                (source_tier_3.pk, 3),
            },
        )

    def test_exclude_test_sources(self):
        source_1 = self.create_source(self.user, name="Source 1")
        for _ in range(2):
            self.upload_image(self.user, source_1)

        test_source_1 = self.create_source(self.user, name="Test 1")
        for _ in range(2):
            self.upload_image(self.user, test_source_1)

        test_source_2 = self.create_source(
            self.user, name="User's temporary source")
        for _ in range(2):
            self.upload_image(self.user, test_source_2)

        ids = {d['sourceId'] for d in cacheable_map_sources.get()}
        self.assertSetEqual(ids, {source_1.pk})

    def test_exclude_no_lat_or_long(self):
        # One 0 is OK
        source_1 = self.create_source(self.user, latitude='0')
        for _ in range(2):
            self.upload_image(self.user, source_1)

        # Either blank: exclude.
        # This is only possible for old sources that were created before
        # lat/long became required in the form.
        test_source_1 = self.create_source(self.user)
        test_source_1.latitude = ''
        test_source_1.save()
        for _ in range(2):
            self.upload_image(self.user, test_source_1)

        test_source_2 = self.create_source(self.user)
        test_source_2.longitude = ''
        test_source_2.save()
        for _ in range(2):
            self.upload_image(self.user, test_source_2)

        # Both 0s: exclude
        test_source_3 = self.create_source(
            self.user, latitude='0', longitude='0')
        for _ in range(2):
            self.upload_image(self.user, test_source_3)

        ids = {d['sourceId'] for d in cacheable_map_sources.get()}
        self.assertSetEqual(ids, {source_1.pk})


@override_settings(MAP_IMAGE_COUNT_TIERS=[2, 3, 5])
class MapSourcesUpdateTest(ClientTest):

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

    @staticmethod
    def run_and_get_result():
        do_job('update_map_sources')
        job = Job.objects.filter(
            job_name='update_map_sources',
            status=Job.Status.SUCCESS).latest('pk')
        return job.result_message

    def test_set_on_demand(self):
        self.assertEqual(len(cacheable_map_sources.get()), 0)

    def test_set_in_advance(self):
        self.assertEqual(
            self.run_and_get_result(), "Updated with 0 map source(s)")
        self.assertEqual(len(cacheable_map_sources.get()), 0)

    def test_set_then_update(self):
        self.assertEqual(
            self.run_and_get_result(), "Updated with 0 map source(s)")
        self.assertEqual(len(cacheable_map_sources.get()), 0)
        for _ in range(2):
            self.upload_image(self.user, self.source)
        self.assertEqual(
            self.run_and_get_result(), "Updated with 1 map source(s)")
        self.assertEqual(len(cacheable_map_sources.get()), 1)

    def test_caching(self):
        self.run_and_get_result()
        self.assertEqual(len(cacheable_map_sources.get()), 0)
        for _ in range(2):
            self.upload_image(self.user, self.source)
        self.assertEqual(len(cacheable_map_sources.get()), 0)
