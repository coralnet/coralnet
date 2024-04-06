from abc import ABC

from django.http import HttpRequest
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils.decorators import method_decorator
from django.views import View

from lib.decorators import debug_required


@method_decorator(
    debug_required,
    name='dispatch')
class QUnitView(View, ABC):

    template_name = 'lib/qunit_running.html'

    # Subclasses can override this if they need a specific template's
    # content for the test runs.
    test_template_name = 'base.html'

    # Subclasses must specify these.
    javascript_functionality_modules: list[str]
    javascript_test_modules: list[str]

    @property
    def default_test_template_context(self):
        """Subclasses can override this as needed."""
        return {}

    def create_test_template_context(self, **kwargs):
        """
        Create a dict which starts with default values, and updates values
        with any passed kwargs.
        """
        context = self.default_test_template_context
        context.update(**kwargs)
        return context

    @property
    def test_template_contexts(self):
        """Subclasses can override this as needed."""
        return {
            'main': {},
        }

    def get(self, request):
        fixtures = dict()

        for fixture_name, context in self.test_template_contexts.items():
            test_template_request = HttpRequest()

            if 'user' in context:
                # Interpret `user` in the given context as specifying
                # request.user
                user = context.pop('user')
                test_template_request.user = user
            else:
                # Use the current admin user
                test_template_request.user = request.user

            fixtures[fixture_name] = render_to_string(
                self.test_template_name, context, test_template_request)

        return render(request, self.template_name, {
            'fixtures': fixtures,
            'javascript_functionality_modules':
                self.javascript_functionality_modules,
            'javascript_test_modules': self.javascript_test_modules,
        })
