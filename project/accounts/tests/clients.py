from typing import Callable
from urllib.parse import parse_qs, urlparse

from django.urls import reverse


class AccountsClientMixin:

    get: Callable
    post: Callable

    @staticmethod
    def activation_key_from_link(link):
        query_args = parse_qs(urlparse(link).query)
        return query_args['activation_key'][0]

    def submit_activation_with_key(self, key):
        return self.post(
            reverse('django_registration_activate'),
            data=dict(activation_key=key),
            follow=True,
        )

    def submit_activation(self, activation_link):
        key = self.activation_key_from_link(activation_link)
        return self.submit_activation_with_key(key)
