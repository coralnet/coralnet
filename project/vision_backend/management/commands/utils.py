from __future__ import unicode_literals
from io import open

from django.utils import timezone


def log(message, filename):
    """ logs message to file """
    now = timezone.now()
    dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
    with open(filename, 'a', encoding='utf-8') as fp:
        message_with_time = "[{}]: {}".format(dt_string, message)
        print(message_with_time)
        fp.write(message_with_time + '\n')
