from django.utils import timezone


def log(message, filename):
    """ logs message to file """
    now = timezone.now()
    dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
    with open(filename, 'a') as fp:
        message_with_time = \
            u"[{}]: {}".format(dt_string, message).encode('utf-8')
        print(message_with_time)
        fp.write(message_with_time + '\n')
