const { test } = QUnit;
import fetchMock from '/static/js/fetch-mock.js';

import { useFixture } from '/static/js/test-utils.js';

let browseActionHelper = null;
let originalWindowAlert = window.alert;
let originalWindowPrompt = window.prompt;


class Form {
    constructor(
        formId,
        actionPath,
        {
            actionFormParams = {},
            expectsSessionDataTimestamp = false,
            hasCsrf = true,
            imageFilters = 'depends on select type',
            promptString = null,
            returnsSessionDataTimestamp = false,
        } = {}) {
        this.formId = formId;
        // Not sure how to pass in URLs from Django, so actionPath is just
        // a hardcoded Django URL.
        this.actionPath = actionPath;
        this.actionFormParams = actionFormParams;
        this.expectsSessionDataTimestamp = expectsSessionDataTimestamp;
        this.hasCsrf = hasCsrf;
        this.imageFilters = imageFilters;
        this.promptString = promptString;
        this.returnsSessionDataTimestamp = returnsSessionDataTimestamp;
    }

    get form() {
        return document.getElementById(this.formId);
    }

    /*
    Check that the part of the form's actual URL after the domain name
    (but including the slash) matches the expected URL.
     */
    assertUrlPathCorrect(assert) {
        // window.location.origin gets the scheme, domain, and port, like:
        // "http://localhost:8000"
        let actualUrl = this.form.action;
        let expectedUrlPath = this.actionPath;
        assert.equal(
            actualUrl, window.location.origin + expectedUrlPath,
            "URL path should be as expected");
    }

    assertFormDataCorrect(assert, imageSelectType, fixtureName) {
        let formData = new FormData(this.form);
        let actualFormContents = Object.fromEntries(formData.entries());

        // {...<obj>} creates a copy.
        let expectedFormContents = {...this.actionFormParams};
        let idFilter = {image_form_type: 'ids', ids: '1,2,3'};
        let searchFilters = {
            aux1: 'Site A', photo_date_0: 'date_range',
            photo_date_1: '', photo_date_2: '',
            photo_date_3: '2021-01-01', photo_date_4: '2021-06-30',
        };

        if (this.imageFilters === 'depends on select type') {
            if (imageSelectType === 'selected') {
                Object.assign(expectedFormContents, idFilter);
            }
            else if (fixtureName === 'with_search_filters') {
                Object.assign(expectedFormContents, searchFilters);
            }
        }
        else if (this.imageFilters === 'search filters only') {
            if (fixtureName === 'with_search_filters') {
                Object.assign(expectedFormContents, searchFilters);
            }
        }

        if (this.expectsSessionDataTimestamp) {
            expectedFormContents.session_data_timestamp = 'a_timestamp';
        }

        if (this.hasCsrf) {
            // We won't try to match the CSRF token value since it's random.
            assert.true(
                'csrfmiddlewaretoken' in actualFormContents,
                "CSRF token should be present in form");
            delete actualFormContents['csrfmiddlewaretoken'];
        }
        else {
            assert.false(
                'csrfmiddlewaretoken' in actualFormContents,
                "CSRF token should not be present in form");
        }

        assert.deepEqual(
            actualFormContents, expectedFormContents,
            "Form contents should be as expected");
    }

    assertUiStatusCorrect(assert, submissionShouldBeEnabled) {
        let submitButton = this.form.querySelector('button.submit');
        let actionSelectField = document.querySelector(
            'select[name=browse_action]');

        if (submissionShouldBeEnabled) {
            assert.equal(
                submitButton.disabled, false,
                "Submit button should be enabled");
            assert.equal(
                submitButton.textContent, "Go", "Submit button should say Go");
            assert.equal(
                actionSelectField.disabled, false,
                "Action select field should be enabled");
        }
        else {
            assert.equal(
                submitButton.disabled, true, "Submit button should be disabled");
            assert.equal(
                submitButton.textContent, "Working...",
                "Submit button should say Working");
            assert.equal(
                actionSelectField.disabled, true,
                "Action select field should be disabled");
        }
    }

    /*
    Mock window.prompt() so that we don't actually have to interact
    with a prompt dialog. This will fill in the correct prompt.
     */
    mockPromptIfApplicable() {
        if (this.promptString) {
            window.prompt = () => {
                return this.promptString;
            };
        }
    }

    mockAsyncFormSubmit() {
        // Mock window.fetch() so that the request isn't actually made.
        let returnObj = {'success': true};
        if (this.returnsSessionDataTimestamp) {
            returnObj.session_data_timestamp = 'a_timestamp';
        }
        fetchMock.post(
            window.location.origin + this.actionPath,
            returnObj);
    }

    /*
    Modify this form's submit handler such that 1) the core part of the
    existing submit handler is still allowed to run, and 2) navigation to
    the form's action URL ultimately doesn't happen.

    At the end of the submit handler, submit() is called on the form
    element. That is the part that starts URL navigation. So, we overwrite
    submit() here with a function that does not navigate anywhere, and sets
    a flag confirming that the form was submitted.
     */
    mockSynchronousFormSubmit() {
        this.submitted = false;
        this.form.submit = () => {
            this.submitted = true;
        };
    }
    assertNotSubmitted(assert) {
        assert.notOk(
            this.submitted,
            "Synchronous form should not have submitted");
    }
    assertSubmitted(assert) {
        assert.ok(
            this.submitted,
            "Synchronous form should have submitted");
    }
}


function changeAction(newValue) {
    if (newValue === 'annotate_all' || newValue === 'annotate_selected') {
        newValue = 'annotate';
    }
    let actionSelectField = document.querySelector(
        'select[name=browse_action]');
    actionSelectField.value = newValue;
    actionSelectField.dispatchEvent(new Event('change'));
}

function changeImageSelectType(newValue) {
    let imageSelectTypeField = document.querySelector(
        'select[name=image_select_type]');
    imageSelectTypeField.value = newValue;
    imageSelectTypeField.dispatchEvent(new Event('change'));
}

/* Return the IDs of all visible action forms. */
function getVisibleActionFormIds() {
    let actionBox = document.getElementById('action-box');
    let actionForms = actionBox.querySelectorAll('form');
    let visibleActionFormIds = [];
    actionForms.forEach((form) => {
        if (!form.hidden) {
            visibleActionFormIds.push(form.id);
        }
    });
    return visibleActionFormIds;
}


let formLookup = {
    annotate_all: new Form('annotate-all-form', '/annotate_all/'),
    annotate_selected: new Form(
        'annotate-selected-form', '/annotate_selected/',
    ),
    export_metadata: new Form(
        'export-metadata-form', '/source/1/export/metadata/',
    ),
    export_annotations: new Form(
        'export-annotations-prep-form', '/source/1/annotation/export_prep/',
        {actionFormParams: {field1: 'value1'}},
    ),
    export_annotations_cpc: new Form(
        'export-annotations-cpc-prep-form',
        '/source/1/cpce/export_prep/',
        {returnsSessionDataTimestamp: true,
         actionFormParams: {field1: 'value1'}},
    ),
    export_image_covers: new Form(
        'export-image-covers-prep-form',
        '/source/1/export/image_covers_prep/',
        {actionFormParams: {field1: 'value1'}},
    ),
    export_calcify_rates: new Form(
        'export-calcify-rates-prep-form',
        '/source/1/calcification/stats_export_prep/',
        {actionFormParams: {field1: 'value1'}},
    ),
    delete_images: new Form(
        'delete-images-ajax-form',
        '/source/1/browse/delete_ajax/',
        {promptString: 'delete'},
    ),
    delete_annotations: new Form(
        'delete-annotations-ajax-form',
        '/source/1/annotation/batch_delete_ajax/',
        {promptString: 'delete'},
    ),
}
let secondFormLookup = {
    export_annotations: new Form(
        'export-serve-form', '/source/1/export/serve/',
        {expectsSessionDataTimestamp: true,
         hasCsrf: false, imageFilters: 'none'},
    ),
    export_annotations_cpc: new Form(
        'export-serve-form', '/source/1/export/serve/',
        {expectsSessionDataTimestamp: true,
         hasCsrf: false, imageFilters: 'none'},
    ),
    export_image_covers: new Form(
        'export-serve-form', '/source/1/export/serve/',
        {expectsSessionDataTimestamp: true,
         hasCsrf: false, imageFilters: 'none'},
    ),
    export_calcify_rates: new Form(
        'export-serve-form', '/source/1/export/serve/',
        {expectsSessionDataTimestamp: true,
         hasCsrf: false, imageFilters: 'none'},
    ),
    delete_images: new Form(
        'refresh-browse-form', '',
        {imageFilters: 'search filters only'},
    ),
    delete_annotations: new Form(
        'refresh-browse-form', '',
        {imageFilters: 'search filters only'},
    ),
}


// QUnit module syntax: https://api.qunitjs.com/QUnit/module/

QUnit.module("Constructor", (hooks) => {
    hooks.beforeEach(() => {
        useFixture('all_images');
    });

    test("Main constructor should succeed", function(assert) {
        browseActionHelper = new BrowseActionHelper([1, 2, 3]);
        assert.ok(browseActionHelper, "Constructor should get initialized");
    });
});


/* Having no labelset makes some forms unavailable, which should at least
not cause errors. */
QUnit.module("Constructor with no labelset", (hooks) => {
    hooks.beforeEach(() => {
        useFixture('no_labelset');
    });

    test("Main constructor should succeed", function(assert) {
        browseActionHelper = new BrowseActionHelper([1, 2, 3]);
        assert.ok(browseActionHelper, "Constructor should get initialized");
    });
});


/* Test that when each particular action is selected, the appropriate
action form is shown. */
QUnit.module("Form visibility", (hooks) => {
    hooks.beforeEach(() => {
        useFixture('all_images');
        browseActionHelper = new BrowseActionHelper([1, 2, 3]);
    });

    test("No action", (assert) => {
        changeAction('annotate');
        changeAction('');
        assert.deepEqual(
            getVisibleActionFormIds(), [],
            "Should have no visible action form when no action is chosen");
    });

    test("Annotate all", (assert) => {
        changeAction('annotate');
        changeImageSelectType('all');
        assert.deepEqual(
            getVisibleActionFormIds(), [formLookup.annotate_all.formId],
            "Should show the appropriate action form for the selections");
    });

    test("Annotate selected", (assert) => {
        changeAction('annotate');
        changeImageSelectType('selected');
        assert.deepEqual(
            getVisibleActionFormIds(), [formLookup.annotate_selected.formId],
            "Should show the appropriate action form for the selections");
    });

    // https://api.qunitjs.com/QUnit/test.each/
    test.each(
            "Export and management actions",
            [
                'export_metadata',
                'export_annotations',
                'export_annotations_cpc',
                'export_image_covers',
                'export_calcify_rates',
                'delete_images',
                'delete_annotations',
            ],
            (assert, actionValue) => {
        changeAction(actionValue);
        assert.deepEqual(
            getVisibleActionFormIds(), [formLookup[actionValue].formId],
            "Should show the appropriate action form for the selections");
    });
});


QUnit.module("Confirmation prompts", (hooks) => {
    hooks.beforeEach(() => {
        useFixture('with_search_filters');
        browseActionHelper = new BrowseActionHelper([1, 2, 3]);
    });
    hooks.afterEach(() => {
        // Restore fetch() to its native implementation
        fetchMock.reset();
        // Restore prompt() to its native implementation
        window.prompt = originalWindowPrompt;
    });

    test.each(
            "No input",
            [
                ['delete_images', 'all'],
                ['delete_images', 'selected'],
                ['delete_annotations', 'all'],
                ['delete_annotations', 'selected'],
            ],
            (assert, [actionValue, imageSelectType]) => {

        changeAction(actionValue);
        changeImageSelectType(imageSelectType);
        let form = formLookup[actionValue];

        form.assertUrlPathCorrect(assert);

        // Mock window.prompt() so that we don't actually have to interact
        // with a prompt dialog.
        window.prompt = () => {
            // Enter nothing for the prompt input.
            return "";
        };

        // Submit.
        let promise = browseActionHelper.actionSubmit(new Event('dummyevent'));

        assert.notOk(promise, "Submission shouldn't have gone through");
        form.assertUiStatusCorrect(assert, true);
    });

    test.each(
            "Wrong input",
            [
                ['delete_images', 'all'],
                ['delete_images', 'selected'],
                ['delete_annotations', 'all'],
                ['delete_annotations', 'selected'],
            ],
            (assert, [actionValue, imageSelectType]) => {

        changeAction(actionValue);
        changeImageSelectType(imageSelectType);
        let form = formLookup[actionValue];

        form.assertUrlPathCorrect(assert);

        // Mock window.prompt() so that we don't actually have to interact
        // with a prompt dialog.
        window.prompt = () => {
            // Use a wrong input: the correct input plus one character.
            return form.promptString + "x";
        };

        // Submit.
        let promise = browseActionHelper.actionSubmit(new Event('dummyevent'));

        assert.notOk(promise, "Submission shouldn't have gone through");
        form.assertUiStatusCorrect(assert, true);
    });

    // Correct input is covered in the form submission tests.
});


/* Test submission of each form, asserting what params were submitted and
 to what URL, and how responses are handled. */
QUnit.module("Form submission", (hooks) => {
    hooks.afterEach(() => {
        // Restore fetch() to its native implementation
        fetchMock.reset();
        // Restore alert() and prompt() to native implementations
        window.alert = originalWindowAlert;
        window.prompt = originalWindowPrompt;
    });

    test.each(
            "Synchronous actions",
            [
                ['annotate_all', 'all', 'all_images'],
                ['annotate_all', 'all', 'with_search_filters'],
                ['annotate_selected', 'selected', 'all_images'],
                ['annotate_selected', 'selected', 'with_search_filters'],
                ['export_metadata', 'all', 'all_images'],
                ['export_metadata', 'selected', 'all_images'],
                ['export_metadata', 'all', 'with_search_filters'],
                ['export_metadata', 'selected', 'with_search_filters'],
            ],
            (assert, [actionValue, imageSelectType, fixtureName]) => {

        useFixture(fixtureName);
        browseActionHelper = new BrowseActionHelper([1, 2, 3]);

        changeAction(actionValue);
        changeImageSelectType(imageSelectType);
        let form = formLookup[actionValue];

        // Ensure that using the submit button doesn't actually navigate
        // to the URL.
        form.mockSynchronousFormSubmit();
        // Run the submit handler.
        // JS console gets a deprecation warning when dispatching an 'untrusted
        // submit event', so just call the submit handler directly.
        browseActionHelper.actionSubmit(new Event('dummyevent'));

        form.assertSubmitted(assert);
        form.assertUrlPathCorrect(assert);
        form.assertFormDataCorrect(assert, imageSelectType, fixtureName);
    });

    test.each(
            "Async actions: request",
            [
                ['export_annotations', 'all', 'all_images'],
                ['export_annotations', 'selected', 'all_images'],
                ['export_annotations', 'all', 'with_search_filters'],
                ['export_annotations', 'selected', 'with_search_filters'],
                ['export_annotations_cpc', 'all', 'all_images'],
                ['export_annotations_cpc', 'selected', 'all_images'],
                ['export_annotations_cpc', 'all', 'with_search_filters'],
                ['export_annotations_cpc', 'selected', 'with_search_filters'],
                ['export_image_covers', 'all', 'all_images'],
                ['export_image_covers', 'selected', 'all_images'],
                ['export_image_covers', 'all', 'with_search_filters'],
                ['export_image_covers', 'selected', 'with_search_filters'],
                ['export_calcify_rates', 'all', 'all_images'],
                ['export_calcify_rates', 'selected', 'all_images'],
                ['export_calcify_rates', 'all', 'with_search_filters'],
                ['export_calcify_rates', 'selected', 'with_search_filters'],
                // Deletion can't be tested with all_images, because deletion
                // has a safety measure against accidentally deleting all
                // images.
                ['delete_images', 'all', 'with_search_filters'],
                ['delete_images', 'selected', 'with_search_filters'],
                ['delete_annotations', 'all', 'with_search_filters'],
                ['delete_annotations', 'selected', 'with_search_filters'],
            ],
            (assert, [actionValue, imageSelectType, fixtureName]) => {

        useFixture(fixtureName);
        browseActionHelper = new BrowseActionHelper([1, 2, 3]);

        changeAction(actionValue);
        changeImageSelectType(imageSelectType);
        let form = formLookup[actionValue];
        let secondForm = secondFormLookup[actionValue];

        form.assertUrlPathCorrect(assert);

        form.mockPromptIfApplicable();
        form.mockAsyncFormSubmit();
        secondForm.mockSynchronousFormSubmit();

        // Submit.
        let promise = browseActionHelper.actionSubmit(new Event('dummyevent'));

        // Check UI status before response.
        form.assertUiStatusCorrect(assert, false);

        // Test what was submitted for the async request.
        form.assertFormDataCorrect(assert, imageSelectType, fixtureName);

        // Wait for the response.
        const done = assert.async();
        promise.then((response) => {
            secondForm.assertSubmitted(assert);

            // Tell QUnit that the test can finish.
            done();
        });
    });

    test.each(
            "Async actions: success response",
            [
                ['export_annotations_cpc', 'all', 'all_images'],
                ['export_annotations_cpc', 'selected', 'all_images'],
                ['export_annotations_cpc', 'all', 'with_search_filters'],
                ['export_annotations_cpc', 'selected', 'with_search_filters'],
                ['delete_images', 'all', 'with_search_filters'],
                ['delete_images', 'selected', 'with_search_filters'],
                ['delete_annotations', 'all', 'with_search_filters'],
                ['delete_annotations', 'selected', 'with_search_filters'],
            ],
            (assert, [actionValue, imageSelectType, fixtureName]) => {

        useFixture(fixtureName);
        browseActionHelper = new BrowseActionHelper([1, 2, 3]);

        changeAction(actionValue);
        changeImageSelectType(imageSelectType);
        let form = formLookup[actionValue];
        let secondForm = secondFormLookup[actionValue];

        form.mockPromptIfApplicable();
        form.mockAsyncFormSubmit();
        secondForm.mockSynchronousFormSubmit();

        // Submit.
        let promise = browseActionHelper.actionSubmit(new Event('dummyevent'));

        // Wait for the response.
        const done = assert.async();
        promise.then((response) => {
            // Check UI status after the response comes back.
            form.assertUiStatusCorrect(assert, true);

            secondForm.assertSubmitted(assert);

            // Test what was submitted for the sync request.
            secondForm.assertFormDataCorrect(
                assert, imageSelectType, fixtureName);

            // Tell QUnit that the test can finish.
            done();
        });
    });

    test.each(
            "Async actions: failure response",
            [
                ['export_annotations_cpc', 'all', 'all_images'],
                ['export_annotations_cpc', 'selected', 'all_images'],
                ['export_annotations_cpc', 'all', 'with_search_filters'],
                ['export_annotations_cpc', 'selected', 'with_search_filters'],
                ['delete_images', 'all', 'with_search_filters'],
                ['delete_images', 'selected', 'with_search_filters'],
                ['delete_annotations', 'all', 'with_search_filters'],
                ['delete_annotations', 'selected', 'with_search_filters'],
            ],
            async(assert, [actionValue, imageSelectType, fixtureName]) => {

        useFixture(fixtureName);
        browseActionHelper = new BrowseActionHelper([1, 2, 3]);

        changeAction(actionValue);
        changeImageSelectType(imageSelectType);
        let form = formLookup[actionValue]

        form.mockPromptIfApplicable();

        // Mock window.fetch() so that the request isn't actually made.
        // Response should indicate a server error.
        fetchMock.post(
            window.location.origin + form.actionPath,
            new Response(
                null, {status: 500, statusText: "Internal Server Error"}));

        // Mock window.alert() so that we don't actually have to interact
        // with an alert dialog. Also, so we can assert its contents.
        let alertMessage = null;
        window.alert = (message) => {
            alertMessage = message;
        };
        // Be able to check if the sync form submitted or not (it shouldn't).
        let secondForm = secondFormLookup[actionValue];
        secondForm.mockSynchronousFormSubmit();

        // Submit.
        let errorMessage;
        await browseActionHelper.actionSubmit(new Event('dummyevent'))
            .catch((error) => {
                errorMessage = error.message;
            });

        secondForm.assertNotSubmitted(assert);

        assert.equal(
            alertMessage,
            "There was an error:" +
            "\nError: Internal Server Error" +
            "\nIf the problem persists, please notify us on the forum.",
            "Alert message should be as expected");
        assert.equal(
            errorMessage,
            "Internal Server Error",
            "Should throw the expected error");
    });
});
