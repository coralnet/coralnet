from __future__ import unicode_literals


class ApiRequestDataError(Exception):
    """
    Error regarding the data passed in an API request. Doesn't match the
    expected format, number values are beyond the max/min allowed, etc.

    Sets an error_dict attribute which follows the jsonapi.org format for error
    objects.
    """
    def __init__(self, message, json_path=None, parameter=None):
        """
        :param message: The error message. Used in the 'detail' member.
        :param json_path: A list corresponding to a JSON pointer
          (https://tools.ietf.org/html/rfc6901). For example, ['abc', 0, 'def']
          corresponds to '/abc/0/def'.
        :param parameter: Name of the request parameter associated with the
          error.
        """
        source_dict = dict()
        if json_path:
            source_dict['pointer'] = ''.join(
                ['/' + str(part) for part in json_path])
        if parameter:
            source_dict['parameter'] = parameter

        self.error_dict = dict(detail=message)
        if source_dict:
            self.error_dict['source'] = source_dict
