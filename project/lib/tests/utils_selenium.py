from contextlib import contextmanager

from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import skipIfDBFeature, tag
from django.urls import reverse

from .utils import ClientTest


class EC_alert_is_not_present(object):
    """Selenium expected condition: An alert is NOT present.
    Based on the built-in alert_is_present."""
    def __init__(self):
        pass

    def __call__(self, driver):
        try:
            alert = driver.switch_to.alert
            # Accessing the alert text could throw a NoAlertPresentException
            _ = alert.text
            return False
        except NoAlertPresentException:
            return True


class EC_javascript_global_var_value(object):
    """Selenium expected condition: A global Javascript variable
    has a particular value."""
    def __init__(self, var_name, expected_value):
        self.var_name = var_name
        self.expected_value = expected_value

    def __call__(self, driver):
        return driver.execute_script(
            'return (window.{} === {})'.format(
                self.var_name, self.expected_value))


@tag('selenium')
@skipIfDBFeature('test_db_allows_multiple_connections')
class BrowserTest(StaticLiveServerTestCase, ClientTest):
    """
    Unit testing class for running tests in the browser with Selenium.
    Selenium reference: https://selenium-python.readthedocs.io/api.html

    You can skip these tests like `manage.py test --exclude-tag selenium`.

    Explanation of the inheritance scheme and
    @skipIfDBFeature('test_db_allows_multiple_connections'):
    This class inherits StaticLiveServerTestCase for the live-server
    functionality, and (a subclass of) TestCase to achieve test-function
    isolation using uncommitted transactions.
    StaticLiveServerTestCase does not have the latter feature. The reason is
    that live server tests use separate threads, which may use separate
    DB connections, which may end up in inconsistent states. To avoid
    this, it inherits from TransactionTestCase, which makes each connection
    commit all their transactions.
    But if there is only one DB connection possible, like with SQLite
    (which is in-memory for Django tests), then this inconsistency concern
    is not present, and we can use TestCase's feature. Hence the decorator:
    @skipIfDBFeature('test_db_allows_multiple_connections')
    Which ensures that these tests are skipped for PostgreSQL, MySQL, etc.,
    but are run if the DB backend setting is SQLite.
    Finally, we really want TestCase because:
    1) Our migrations have initial data in them, such as Robot and Alleviate
    users, and for some reason this data might get erased (and not re-created)
    between tests if TestCase is not used.
    2) The ClientUtilsMixin's utility methods are all classmethods which are
    supposed to be called in setUpTestData(). TestCase is what provides the
    setUpTestData() hook.
    Related discussions:
    https://code.djangoproject.com/ticket/23640
    https://stackoverflow.com/questions/29378328/
    """
    selenium = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Selenium driver.
        # TODO: Look into running tests with multiple browsers. Right now it
        # just runs the first specified browser in SELENIUM_BROWSERS.
        # Test parametrization idea 1:
        # https://docs.pytest.org/en/latest/parametrize.html
        # https://twitter.com/audreyr/status/702540511425396736
        # Test parametrization idea 2: https://stackoverflow.com/a/40982410/
        # Decorator idea: https://stackoverflow.com/a/26821662/
        for browser in settings.SELENIUM_BROWSERS:
            browser_name_lower = browser['name'].lower()

            if browser_name_lower == 'firefox':
                options = FirefoxOptions()
                for option in browser.get('options', []):
                    options.add_argument(option)
                cls.selenium = webdriver.Firefox(
                    firefox_binary=browser.get('browser_binary', None),
                    executable_path=browser.get('webdriver', 'geckodriver'),
                    firefox_options=options,
                )
                break

            if browser_name_lower == 'chrome':
                options = ChromeOptions()
                for option in browser.get('options', []):
                    options.add_argument(option)
                # Seems like the Chrome driver doesn't support a browser
                # binary argument.
                cls.selenium = webdriver.Chrome(
                    executable_path=browser.get('webdriver', 'chromedriver'),
                    chrome_options=options,
                )
                break

            if browser_name_lower == 'phantomjs':
                cls.selenium = webdriver.PhantomJS(
                    executable_path=browser.get('webdriver', 'phantomjs'),
                )
                break

        # These class-var names should be nicer for autocomplete usage.
        cls.TIMEOUT_DB_CONSISTENCY = \
            settings.SELENIUM_TIMEOUTS['db_consistency']
        cls.TIMEOUT_SHORT = settings.SELENIUM_TIMEOUTS['short']
        cls.TIMEOUT_MEDIUM = settings.SELENIUM_TIMEOUTS['medium']
        cls.TIMEOUT_PAGE_LOAD = settings.SELENIUM_TIMEOUTS['page_load']

        # The default timeout here can be quite long, like 300 seconds.
        cls.selenium.set_page_load_timeout(cls.TIMEOUT_PAGE_LOAD)

    @classmethod
    def tearDownClass(cls):
        cls.selenium.quit()

        super().tearDownClass()

    @contextmanager
    def wait_for_page_load(self, old_element=None):
        """
        Implementation from:
        http://www.obeythetestinggoat.com/how-to-get-selenium-to-wait-for-page-load-after-a-click.html

        Limitations:

        - "Note that this solution only works for "non-javascript" clicks,
        ie clicks that will cause the browser to load a brand new page,
        and thus load a brand new HTML body element."

        - Getting old_element and checking for staleness of it won't work
        if an alert is present. You'll get an unexpected alert exception.
        If you expect to have an alert present when starting this context
        manager, you should pass in an old_element, and wait until the alert
        is no longer present before finishing this context manager's block.

        - This doesn't wait for on-page-load Javascript to run. That will need
        to be checked separately.
        """
        if not old_element:
            old_element = self.selenium.find_element_by_tag_name('html')
        yield
        WebDriverWait(self.selenium, self.TIMEOUT_PAGE_LOAD) \
            .until(EC.staleness_of(old_element))

    def get_url(self, url):
        """
        url is something like `/login/`. In general it can be a result of
        reverse().
        """
        self.selenium.get('{}{}'.format(self.live_server_url, url))

    def login(self, username, password, stay_signed_in=False):
        self.get_url(reverse('login'))
        username_input = self.selenium.find_element_by_name("username")
        username_input.send_keys(username)
        password_input = self.selenium.find_element_by_name("password")
        password_input.send_keys(password)

        if stay_signed_in:
            # Tick the checkbox
            stay_signed_in_input = \
                self.selenium.find_element_by_name("stay_signed_in")
            stay_signed_in_input.click()

        with self.wait_for_page_load():
            self.selenium.find_element_by_css_selector(
                'input[value="Sign in"]').click()
