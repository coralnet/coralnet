const { test } = QUnit;
import fetchMock from '/static/js/fetch-mock.js';

import { useFixture } from '/static/js/test-utils.js';

let originalWindowAlert = window.alert;


QUnit.module("fetch", (hooks) => {
    hooks.beforeEach(async() => {
        useFixture('main');
    });
    hooks.afterEach(() => {
        // Restore fetch() to its native implementation
        fetchMock.reset();
        // Restore alert() to its native implementation
        window.alert = originalWindowAlert;
    });

    test("success without callback", async function(assert) {
        fetchMock.get(
            {url: '/test-url'},
            // Response config as JSON
            {testKey: 'test_value'},
        );

        let responseJson = await util.fetch(
            '/test-url',
            {method: 'GET'},
        );
        assert.deepEqual(
            responseJson, {testKey: 'test_value'},
            "Response should be as expected");
    });

    test("success with callback", async function(assert) {
        fetchMock.get(
            {url: '/test-url'},
            {testKey: 'test_value'},
        );

        let callbackObj = await util.fetch(
            '/test-url',
            {method: 'GET'},
            (responseJson) => {
                let obj = responseJson
                obj.testKey2 = 'test_value_2';
                return obj
            }
        );
        assert.deepEqual(
            callbackObj, {testKey: 'test_value', testKey2: 'test_value_2'},
            "Object returned from the callback should be as expected");
    });

    test("server error", async function(assert) {
        fetchMock.get(
            {url: '/test-url'},
            // Response config as a Response instance
            new Response(null, {
                status: 500, statusText: "Internal server error"}),
        );

        // Mock window.alert() so that we don't actually have to interact
        // with an alert dialog. Also, so we can assert its contents.
        let alertMessage;
        window.alert = (message) => {
            alertMessage = message;
        };

        let errorMessage;
        await util.fetch(
            '/test-url',
            {method: 'GET'},
        )
            .catch((error) => {
                errorMessage = error.message;
            });

        assert.equal(
            alertMessage,
            "There was an error:" +
            "\nError: Internal server error" +
            "\nIf the problem persists, please notify us on the forum.",
            "Should alert with the expected message");
        assert.equal(
            errorMessage,
            "Internal server error",
            "Should throw the expected error");
    });

    test("server responds with non-JSON", async function(assert) {
        fetchMock.get(
            {url: '/test-url'},
            new Response(),
        );

        // Mock window.alert() so that we don't actually have to interact
        // with an alert dialog. Also, so we can assert its contents.
        let alertMessage;
        window.alert = (message) => {
            alertMessage = message;
        };

        let errorMessage;
        await util.fetch(
            '/test-url',
            {method: 'GET'},
        )
            .catch((error) => {
                errorMessage = error.message;
            });

        assert.equal(
            alertMessage,
            "There was an error:" +
            "\nSyntaxError: JSON.parse: unexpected end of data at" +
            " line 1 column 1 of the JSON data" +
            "\nIf the problem persists, please notify us on the forum.",
            "Should alert with the expected message");
        assert.equal(
            errorMessage,
            "JSON.parse: unexpected end of data at line 1 column 1" +
            " of the JSON data",
            "Should throw the expected error");
    });

    test("callback error", async function(assert) {
        fetchMock.get(
            {url: '/test-url'},
            {testKey: 'test_value'},
        );

        // Mock window.alert() so that we don't actually have to interact
        // with an alert dialog. Also, so we can assert its contents.
        let alertMessage;
        window.alert = (message) => {
            alertMessage = message;
        };

        let errorMessage;
        await util.fetch(
            '/test-url',
            {method: 'GET'},
            (responseJson) => {
                throw new Error(`Response value was ${responseJson.testKey}`);
            },
        )
            .catch((error) => {
                errorMessage = error.message;
            });

        assert.equal(
            alertMessage,
            "There was an error:" +
            "\nError: Response value was test_value" +
            "\nIf the problem persists, please notify us on the forum.",
            "Should alert with the expected message");
        assert.equal(
            errorMessage,
            "Response value was test_value",
            "Should throw the expected error");
    });
});
