from django.core.management.base import BaseCommand

from vision_backend.task_helpers import _read_message


class Command(BaseCommand):
    help = 'Read all spacer error messages. Deletes messages after they are displayed.'

    def handle(self, *args, **options):
        self.read_error_messages()

    def read_error_messages(self):
        message = _read_message('spacer_errors')
        while not message == None:
            print message.get_body()
            message.delete()
            message = _read_message('spacer_errors')