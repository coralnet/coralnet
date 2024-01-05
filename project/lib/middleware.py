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

        # One-time configuration and initialization.
        self.active_views = set()

    @classmethod
    def get_next_view_id(cls):
        return str(uuid.uuid4())

    @staticmethod
    def log_info(tokens):
        message = ';'.join(str(token) for token in tokens)
        view_logger.info(message)

    @staticmethod
    def log_debug(tokens):
        message = ';'.join(str(token) for token in tokens)
        view_logger.debug(message)

    def __call__(self, request: HttpRequest):
        # Before-view code.
        view_id = self.get_next_view_id()
        self.active_views.add(view_id)
        view_path = request.path
        view_name = resolve(view_path).view_name
        self.log_debug([
            view_id,
            'start',
            len(self.active_views),
            '',
            '',
            '',
            request.method,
            request.user.pk,
            view_path,
        ])
        start_time = datetime.datetime.now()

        response: HttpResponse = self.get_response(request)

        # After-view code.
        elapsed_seconds = (datetime.datetime.now() - start_time).total_seconds()
        if elapsed_seconds > 0.5:
            log = self.log_info
        else:
            log = self.log_debug
        self.active_views.remove(view_id)
        log([
            view_id,
            'end',
            len(self.active_views),
            elapsed_seconds,
            view_name,
            response.status_code,
            request.method,
            request.user.pk,
            view_path,
        ])

        return response
