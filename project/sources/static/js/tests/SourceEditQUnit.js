const { test } = QUnit;

import MultiValueFieldHelper from '/static/js/MultiValueFieldHelper.js';
import SourceFormHelper from '/static/js/SourceFormHelper.js';
import { useFixture } from '/static/js/test-utils.js';

let sourceFormHelper;
let originalWindowConfirm = window.confirm;


function changePointGenType(newValue) {
    let typeField = document.getElementById(
        'id_default_point_generation_method_0');
    typeField.value = newValue;
    typeField.dispatchEvent(new Event('change'));
}


function setUp() {
    let sourceForm = document.getElementById('source-form');
    MultiValueFieldHelper.setUpFieldBasedVisibility(sourceForm);
    sourceFormHelper = new SourceFormHelper();
}


/* This test could've applied to either source new or source edit. */
QUnit.module("Point generation method", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');
        setUp();
    });
    hooks.afterEach(() => {
    });

    test("starting visibility", async function(assert) {
        // The test template should start out with simple random.
        // type and points should be not hidden, and the other 3 fields
        // should be hidden.
        assert.false(document.getElementById(
            'id_default_point_generation_method_0').hidden);
        assert.false(document.getElementById(
            'id_default_point_generation_method_1').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_2').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_3').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_4').hidden);
    });

    test("simple random", async function(assert) {
        // To differentiate this from the starting visibility test,
        // change to something besides simple random, then change back
        // to simple random, and then check visibility.

        changePointGenType('t');
        changePointGenType('m');

        assert.false(document.getElementById(
            'id_default_point_generation_method_0').hidden);
        assert.false(document.getElementById(
            'id_default_point_generation_method_1').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_2').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_3').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_4').hidden);
    });

    test("stratified random", async function(assert) {
        changePointGenType('t');

        assert.false(document.getElementById(
            'id_default_point_generation_method_0').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_1').hidden);
        assert.false(document.getElementById(
            'id_default_point_generation_method_2').hidden);
        assert.false(document.getElementById(
            'id_default_point_generation_method_3').hidden);
        assert.false(document.getElementById(
            'id_default_point_generation_method_4').hidden);
    });

    test("uniform grid", async function(assert) {
        changePointGenType('u');

        assert.false(document.getElementById(
            'id_default_point_generation_method_0').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_1').hidden);
        assert.false(document.getElementById(
            'id_default_point_generation_method_2').hidden);
        assert.false(document.getElementById(
            'id_default_point_generation_method_3').hidden);
        assert.true(document.getElementById(
            'id_default_point_generation_method_4').hidden);
    });
});


/* This test is specific to source-edit. */
QUnit.module("Extractor setting", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');
        setUp();
    });
    hooks.afterEach(() => {
        // Restore confirm() to its native implementation
        window.confirm = originalWindowConfirm;
    });

    test("extractor change warning location", async function(assert) {
        let warningElement =
            document.getElementById('feature-extractor-change-warning');
        let extractorSettingField =
            document.getElementById('id_feature_extractor_setting');
        let extractorSettingFieldGrid =
            extractorSettingField.closest('.form-fields-grid');

        assert.strictEqual(
            extractorSettingFieldGrid.parentNode,
            warningElement.parentNode,
            "Warning should be adjacent to the extractor setting field grid");
    });

    test("extractor change warning visibility", async function(assert) {
        let warningElement =
            document.getElementById('feature-extractor-change-warning');
        let extractorSettingField =
            document.getElementById('id_feature_extractor_setting');

        assert.strictEqual(
            extractorSettingField.value, 'efficientnet_b0_ver1',
            "Sanity check: Extractor setting should match template context");
        assert.true(warningElement.hidden, "Warning should be hidden");

        extractorSettingField.value = 'vgg16_coralnet_ver1';
        extractorSettingField.dispatchEvent(new Event('change'));
        assert.false(warningElement.hidden, "Warning should be shown");

        extractorSettingField.value = 'efficientnet_b0_ver1';
        extractorSettingField.dispatchEvent(new Event('change'));
        assert.true(warningElement.hidden, "Warning should be hidden");
    });

    test("submit with extractor change and confirm it", async function(assert) {
        let extractorSettingField =
            document.getElementById('id_feature_extractor_setting');
        extractorSettingField.value = 'vgg16_coralnet_ver1';
        extractorSettingField.dispatchEvent(new Event('change'));

        // Mock window.confirm() so that we don't actually have to interact
        // with a confirmation dialog.
        window.confirm = () => {
            // Yes, confirm it
            return true;
        };

        // Make a mock event which tracks whether preventDefault() was
        // called on it. Basically we're checking the form submission logic
        // without actually submitting the form (which we can't do because
        // that would cause a page load and stop the QUnit tests).
        let defaultPrevented = false;
        let mockEvent = {
            preventDefault: () => {
                defaultPrevented = true;
            },
        }
        sourceFormHelper.submitForm(mockEvent);
        assert.false(
            defaultPrevented,
            "Should not have prevented default"
            + " (i.e. the submission would go through)");
    });

    test("submit with extractor change and don't confirm it", async function(assert) {
        let extractorSettingField =
            document.getElementById('id_feature_extractor_setting');
        extractorSettingField.value = 'vgg16_coralnet_ver1';
        extractorSettingField.dispatchEvent(new Event('change'));

        // Mock window.confirm() so that we don't actually have to interact
        // with a confirmation dialog.
        window.confirm = () => {
            // No, don't confirm it
            return false;
        };

        let defaultPrevented = false;
        let mockEvent = {
            preventDefault: () => {
                defaultPrevented = true;
            },
        }
        sourceFormHelper.submitForm(mockEvent);
        assert.true(
            defaultPrevented,
            "Should have prevented default"
            + " (i.e. the submission would not go through)");
    });

    test("submit with extractor unchanged", async function(assert) {

        let extractorSettingField =
            document.getElementById('id_feature_extractor_setting');
        extractorSettingField.value = 'vgg16_coralnet_ver1';
        extractorSettingField.dispatchEvent(new Event('change'));
        extractorSettingField.value = 'efficientnet_b0_ver1';
        extractorSettingField.dispatchEvent(new Event('change'));

        let defaultPrevented = false;
        let mockEvent = {
            preventDefault: () => {
                defaultPrevented = true;
            },
        }
        sourceFormHelper.submitForm(mockEvent);
        assert.false(
            defaultPrevented,
            "Should not have prevented default"
            + " (i.e. the submission would go through)");
    });
});
