from django.core.management.commands.test import Command as TestCommand


class Command(TestCommand):

    help = "Discover and run Selenium tests."

    def handle(self, *test_labels, **options):
        options['testrunner'] = 'lib.tests.utils_selenium.SeleniumTestRunner'
        super().handle(*test_labels, **options)
