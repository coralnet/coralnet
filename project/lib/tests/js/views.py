from lib.tests.utils_qunit import QUnitView


class UtilQUnitView(QUnitView):

    # These tests don't require anything in particular in the
    # content-container.
    test_template_name = 'base.html'
    # base.html should already include util.
    javascript_functionality_modules = []
    javascript_test_modules = ['js/tests/UtilQUnit.js']

    @property
    def default_test_template_context(self):
        return {}

    @property
    def test_template_contexts(self):
        return {
            'main': {},
        }
