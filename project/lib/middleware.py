import datetime
from logging import getLogger
import uuid

from django.http import HttpRequest, HttpResponse
from django.urls import resolve

view_logger = getLogger('coralnet_views')


class ViewLoggingMiddleware:
    """
    Log when each view starts and ends.
    Kind of like nginx request logging, except that here we only care about
    requests that are delegated to the Django server.
    This helps to narrow down the causes of poor server performance.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def log_info(tokens):
        message = ';'.join(str(token) for token in tokens)
        view_logger.info(message)

    @staticmethod
    def log_debug(tokens):
        message = ';'.join(str(token) for token in tokens)
        view_logger.debug(message)

    def __call__(self, request: HttpRequest):
        # Log a message before view entry.
        view_id = str(uuid.uuid4())
        view_path = request.path
        view_name = resolve(view_path).view_name
        view_user = request.user.pk or "Guest"
        self.log_debug([
            view_id,
            # view or task.
            'view',
            # start or end.
            'start',
            '',
            view_name,
            '',
            request.method,
            view_user,
            view_path,
        ])
        start_time = datetime.datetime.now()

        response: HttpResponse = self.get_response(request)

        # Log a message after view exit.
        elapsed_seconds = (datetime.datetime.now() - start_time).total_seconds()
        if elapsed_seconds > 0.5:
            log = self.log_info
        else:
            log = self.log_debug
        log([
            view_id,
            'view',
            'end',
            elapsed_seconds,
            view_name,
            response.status_code,
            request.method,
            view_user,
            view_path,
        ])

        return response
