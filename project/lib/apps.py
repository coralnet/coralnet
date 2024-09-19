from django.apps import AppConfig


class LibConfig(AppConfig):
    name = 'lib'

    def ready(self):
        # Implicitly connect signal handlers decorated with @receiver.
        from .tests import signals
