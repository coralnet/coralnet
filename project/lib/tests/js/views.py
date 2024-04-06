from lib.tests.utils_qunit import QUnitView


class PollerQUnitView(QUnitView):

    # Poller.js can be imported by the test module, instead of being
    # specified here.
    javascript_functionality_modules = []
    javascript_test_modules = ['js/tests/PollerQUnit.js']


class UtilQUnitView(QUnitView):

    # base.html should already include util.
    javascript_functionality_modules = []
    javascript_test_modules = ['js/tests/UtilQUnit.js']
