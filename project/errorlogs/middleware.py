import sys
import traceback

from django.http import Http404
from django.views.debug import ExceptionReporter

from .utils import instantiate_error_log


class SaveLogsToDatabaseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.error_log = None

    def __call__(self, request):
        response = self.get_response(request)

        if self.error_log:
            # Now that we're outside of the view's transaction, save any
            # error that was logged earlier.
            self.error_log.save()
            self.error_log = None
        return response

    def process_exception(self, request, exception):
        """
        Handles errors raised during views.
        """
        # Get the most recent exception's info.
        kind, info, data = sys.exc_info()

        if not issubclass(kind, Http404):

            # Create an ErrorLog to save to the database, but don't actually
            # save it yet, since we're still inside of the view's transaction.
            # We'll save it later in __call__() when the view returns.
            error_html = ExceptionReporter(
                request, kind, info, data).get_traceback_html()
            error_data = '\n'.join(traceback.format_exception(kind, info, data))
            self.error_log = instantiate_error_log(
                kind=kind.__name__,
                html=error_html,
                path=request.build_absolute_uri(),
                info=info,
                data=error_data,
            )
