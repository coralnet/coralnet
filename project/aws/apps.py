from django.apps import AppConfig


class AwsConfig(AppConfig):
    name = 'aws'

    def ready(self):
        # Implicitly connect signal handlers decorated with @receiver.
        from .tests import signals
