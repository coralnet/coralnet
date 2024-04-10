from lib.tests.utils_qunit import QUnitView


class AsyncMediaQUnitView(QUnitView):

    test_template_name = 'async_media/async_media_qunit.html'
    # base.html should already include jQuery, util, and AsyncMedia.
    javascript_functionality_modules = []
    javascript_test_modules = ['js/tests/AsyncMediaQUnit.js']
