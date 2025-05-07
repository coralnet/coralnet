const { test } = QUnit;

import BrowseSearchHelper from '/static/js/BrowseSearchHelper.js';
import { useFixture } from '/static/js/test-utils.js';


function setFieldValue(fieldName, newValue) {
    let field = document.querySelector(
        `input[name=${fieldName}], select[name=${fieldName}]`);
    field.value = newValue;
    field.dispatchEvent(new Event('change'));
}

function assertFieldEnabledStatus(assert, fieldName, shouldBeEnabled) {
    let field = document.querySelector(
        `input[name=${fieldName}], select[name=${fieldName}]`);
    assert.equal(
        field.disabled, !shouldBeEnabled,
        `Field enabled status should be ${shouldBeEnabled}`);
}


QUnit.module("Main", (hooks) => {
    hooks.beforeEach(() => {
        useFixture('main');
    });

    test("submit only non-blank fields", (assert) => {
        // Text input elements
        setFieldValue('field_1', 'aaa');
        setFieldValue('field_2', '');
        // Select elements
        setFieldValue('field_3', '');
        setFieldValue('field_4', 'ddd');

        assertFieldEnabledStatus(assert, 'field_1', true);
        assertFieldEnabledStatus(assert, 'field_2', true);
        assertFieldEnabledStatus(assert, 'field_3', true);
        assertFieldEnabledStatus(assert, 'field_4', true);

        let form = document.getElementById('search-form');
        // JS console gets a deprecation warning when dispatching an 'untrusted
        // submit event', so we just call our submit listener directly.
        BrowseSearchHelper.onSearchSubmit(form);

        assertFieldEnabledStatus(assert, 'field_1', true);
        assertFieldEnabledStatus(assert, 'field_2', false);
        assertFieldEnabledStatus(assert, 'field_3', false);
        assertFieldEnabledStatus(assert, 'field_4', true);
    });
});
