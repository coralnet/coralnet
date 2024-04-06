from lib.tests.utils_qunit import QUnitView


class AsyncMediaQUnitView(QUnitView):

    test_template_name = 'async_media/async_media_qunit.html'
    # base.html should already include jQuery, util, and AsyncMedia.
    javascript_functionality_modules = []
    javascript_test_modules = ['js/tests/AsyncMediaQUnit.js']

    @property
    def default_test_template_context(self):
        return {}

    @property
    def test_template_contexts(self):
        return {
            'main': {},
        }
