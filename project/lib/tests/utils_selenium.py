from contextlib import contextmanager

from selenium import webdriver
from selenium.common.exceptions import NoAlertPresentException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.edge.options import Options as EdgeOptions
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import tag
from django.urls import reverse

from .utils import ThreadingCompatibleTest


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
class BaseSeleniumTest(StaticLiveServerTestCase, ThreadingCompatibleTest):
    """
    Unit testing class for running tests in the browser with Selenium.

    This class inherits StaticLiveServerTestCase for the live-server
    functionality. However, StaticLiveServerTestCase inherits from
    TransactionTestCase, and we still want (Django) TestCase for its
    setUpTestData() hook. So we do multiple inheritance with
    StaticLiveServerTestCase + our applicable subclass of TestCase.

    Our applicable subclass of TestCase is ThreadingCompatibleTest, because
    live server tests are always multi-threaded. If we try to do things with
    single-threaded assumptions, such as wrapping the entire test in a
    database transaction, then these tests break.
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
        if len(settings.SELENIUM_BROWSERS) == 0:
            raise ValueError("SELENIUM_BROWSERS is empty.")
        browser = settings.SELENIUM_BROWSERS[0]

        browser_name_lower = browser['name'].lower()

        if browser_name_lower == 'firefox':
            options = FirefoxOptions()
            webdriver_class = webdriver.Firefox
            service_class = webdriver.FirefoxService
            default_webdriver_path = 'geckodriver'
        elif browser_name_lower == 'chrome':
            options = ChromeOptions()
            webdriver_class = webdriver.Chrome
            service_class = webdriver.ChromeService
            default_webdriver_path = 'chromedriver'
        elif browser_name_lower == 'edge':
            options = EdgeOptions()
            webdriver_class = webdriver.Edge
            service_class = webdriver.EdgeService
            default_webdriver_path = 'msedgedriver'
        else:
            raise ValueError(f"Unsupported browser: {browser['name']}")

        for cli_argument in browser.get('cli_args', []):
            options.add_argument(cli_argument)
        if browser_binary := browser.get('browser_binary'):
            options.binary_location = browser_binary

        executable_path = browser.get('webdriver', default_webdriver_path)
        cls.selenium = webdriver_class(
            options=options,
            service=service_class(executable_path=executable_path),
        )

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
            old_element = self.selenium.find_element(By.TAG_NAME, 'html')
        yield
        WebDriverWait(self.selenium, self.TIMEOUT_PAGE_LOAD) \
            .until(EC.staleness_of(old_element))

    def get_url(self, url):
        """
        url is something like `/login/`. In general it can be a result of
        reverse().
        """
        self.selenium.get(f'{self.live_server_url}{url}')

    def login(self, username, password, stay_signed_in=False):
        self.get_url(reverse('login'))
        username_input = self.selenium.find_element(By.NAME, "username")
        username_input.send_keys(username)
        password_input = self.selenium.find_element(By.NAME, "password")
        password_input.send_keys(password)

        if stay_signed_in:
            # Tick the checkbox
            stay_signed_in_input = \
                self.selenium.find_element(By.NAME, "stay_signed_in")
            stay_signed_in_input.click()

        with self.wait_for_page_load():
            self.selenium.find_element(
                By.CSS_SELECTOR, 'input[value="Sign in"]').click()
