from django.core.management.base import BaseCommand

from vision_backend.task_helpers import _read_message


def read_error_messages():
    message = _read_message('spacer_errors')
    while message is not None:
        print message.get_body()
        message.delete()
        message = _read_message('spacer_errors')


class Command(BaseCommand):
    help = 'Read all spacer error messages. Deletes messages after they are displayed.'

    def handle(self, *args, **options):
        read_error_messages()
