import datetime
from unittest import skipIf
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
import urllib.request

from django.conf import settings

from lib.tests.utils import ClientTest


@skipIf(
    not settings.STORAGES['default']['BACKEND']
        == 'aws.storage.MediaStorageS3',
    "Requires S3 storage")
class S3UrlAccessTest(ClientTest):
    """
    Test accessing uploaded S3 objects by URL.
    """
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        cls.user = cls.create_user()
        cls.source = cls.create_source(cls.user)

        # Upload an image using django-storages + boto.
        cls.img = cls.upload_image(
            cls.user, cls.source, image_options=dict(filename='1.png'))

    def assert_forbidden(self, url, msg):
        with self.assertRaises(HTTPError) as cm:
            urllib.request.urlopen(url)
        self.assertEqual(cm.exception.code, 403, msg)

    def test_image_url_query_args(self):
        url = self.img.original_file.url
        current_timestamp = datetime.datetime.now().timestamp()
        query_string = urlsplit(url).query
        query_args = parse_qs(query_string)

        self.assertIn('AWSAccessKeyId', query_args, "Should have an access key")
        self.assertIn('Expires', query_args, "Should have an expire time")
        self.assertIn('Signature', query_args, "Should have a signature")

        expire_timestamp = int(query_args['Expires'][0])
        self.assertGreaterEqual(
            expire_timestamp, current_timestamp + 3300,
            "Expire time should be about 1 hour into the future")
        self.assertLessEqual(
            expire_timestamp, current_timestamp + 3900,
            "Expire time should be about 1 hour into the future")

    def test_image_url_allowed_access(self):
        url = self.img.original_file.url
        base_url = urlunsplit(urlsplit(url)._replace(query=''))
        query_string = urlsplit(url).query
        query_args = parse_qs(query_string)

        response = urllib.request.urlopen(url)
        self.assertEqual(
            response.status, 200, "Getting the URL should work")
        self.assertEqual(
            response.headers['Content-Type'], 'image/png',
            "URL response should have the expected content type")

        alt_query_args = query_args.copy()
        alt_query_args.pop('AWSAccessKeyId')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL without the access key shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args.pop('Expires')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL without the expire time shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args.pop('Signature')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL without the signature shouldn't work")

        self.assert_forbidden(
            base_url,
            "Getting the URL without any query args shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args['AWSAccessKeyId'][0] = \
            alt_query_args['AWSAccessKeyId'][0].replace(
                alt_query_args['AWSAccessKeyId'][0][5], 'X')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL with a modified access key shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args['Expires'][0] = \
            alt_query_args['Expires'][0].replace(
                alt_query_args['Expires'][0][5], '0')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL with a modified expire time shouldn't work")

        alt_query_args = query_args.copy()
        alt_query_args['Signature'][0] = \
            alt_query_args['Signature'][0].replace(
                alt_query_args['Signature'][0][5], 'X')
        self.assert_forbidden(
            base_url + '?' + urlencode(alt_query_args),
            "Getting the URL with a modified signature shouldn't work")
