const { test } = QUnit;
import fetchMock from '/static/js/fetch-mock.js';

import { useFixture } from '/static/js/test-utils.js';

let originalWindowConfirm = window.confirm;


async function makeImageFile(filename) {
    // Set up canvas to hold pixel data
    // https://stackoverflow.com/questions/5867723/javascript-image-manipulation-pixel-by-pixel
    let canvas = document.createElement('canvas');
    canvas.width = 40;
    canvas.height = 30;
    let context = canvas.getContext('2d');
    let imageData = context.getImageData(0, 0, 40, 30);

    // Set pixel data
    // https://developer.mozilla.org/en-US/docs/Web/API/ImageData/data
    for (let i = 0; i < imageData.data.length; i += 4) {
        // red, green, blue, alpha
        imageData.data[i] = 64;
        imageData.data[i+1] = 192;
        imageData.data[i+2] = 64;
        imageData.data[i+3] = 255;
    }
    context.putImageData(imageData, 0, 0);

    // Convert canvas data to image file
    // https://stackoverflow.com/a/64463046
    let {promise, resolve, _} = Promise.withResolvers();
    canvas.toBlob((blob) => {
        resolve(new File(
            [blob],
            filename,
            {type: 'image/jpeg'},
        ));
    }, 'image/jpeg');
    let imageFile = await promise;

    return imageFile;
}


/*
Set image file in file field, thus triggering a preview request.
https://stackoverflow.com/questions/17063709/how-to-append-a-file-into-a-file-input-field
 */
function setFiles(imageFiles) {
    let dataTransfer = new DataTransfer();
    imageFiles.forEach((imageFile) => {
        dataTransfer.items.add(imageFile);
    });

    let filesField = document.getElementById('id_files');
    filesField.files = dataTransfer.files;
    filesField.dispatchEvent(new Event('change'));
}


/*
Get a Promise that'll be fulfilled once handleUploadPreviewResponse() runs.
 */
function observePreviewHandler() {
    // handleUploadPreviewResponse() empties and then re-fills
    // preUploadSummary. So, when that element's children change,
    // that tells us the handler has run.
    //
    // Specifically, resolve() should get called after the preview handler
    // has finished. Because from the time the handler starts changing
    // preUploadSummary to the time the handler finishes, there shouldn't
    // be any reason for that thread to relinquish control.
    return observeElementChanges(
        document.getElementById('pre_upload_summary'));
}


/*
Get a Promise that'll be fulfilled once handleUploadResponse() runs
for a particular file.
 */
function observeUploadHandler(fileIndex) {
    let filesTable = document.getElementById('files_table');
    return observeElementChanges(
        filesTable.querySelectorAll('td.status_cell')[fileIndex]);
}


function observeElementChanges(element) {
    let {promise, resolve} = Promise.withResolvers();

    let mutationObserver = new MutationObserver(() => {
        resolve();
    });
    mutationObserver.observe(element, {childList: true, subtree: true});

    return promise;
}


function assertStatusDisplay(assert, expectedText) {
    let statusDisplay = document.getElementById('status_display');
    assert.equal(
        statusDisplay.textContent, expectedText,
        "Status display should be as expected");
}


function assertButtonState(
    assert, button, {hidden=null, disabled=null, name=null}
) {
    if (hidden === null || disabled === null) {
        throw new Error("Must specify hidden and disabled booleans.");
    }

    let buttonHidden = button.style.display === 'none';
    let buttonString = name ? `${name} button` : "Button";

    assert.equal(
        buttonHidden, hidden,
        `${buttonString} ${hidden ? "should" : "should not"} be hidden`);
    assert.equal(
        button.disabled, disabled,
        `${buttonString} ${disabled ? "should" : "should not"} be disabled`);
}


function assertTableValues(
    assert, table,
    // Array.<Object|Array>.string
    expectedContents,
) {
    // Get column names from the th elements in the thead.
    let columnNames =
        Array.from(table.querySelectorAll('thead th'))
        .map((th) => th.textContent);
    // Only check body rows (from the tbody part of the table).
    let bodyRows = table.querySelectorAll('tbody > tr');

    assert.equal(
        bodyRows.length, expectedContents.length,
        "Should have expected number of table body rows")

    for (let rowIndex = 0; rowIndex < bodyRows.length; rowIndex++) {
        let row = bodyRows[rowIndex];
        let expectedRow = expectedContents[rowIndex];
        assertRowValues(assert, row, expectedRow, columnNames, rowIndex);
    }
}


function assertRowValues(assert, row, expectedRow, columnNames, rowIndex) {
    let cells = row.querySelectorAll('td');
    let cellsContents = Array.from(cells).map((cell) => cell.outerHTML);

    if (expectedRow instanceof Array) {
        // expectedRow is an array of all the cells' content
        // as HTML strings.
        for (let cellIndex = 0; cellIndex < cellsContents.length; cellIndex++) {
            let actualHtml = cellsContents[cellIndex];
            let expectedHtml = expectedRow[cellIndex];

            // Any element specified as null is considered a
            // "don't care" value which shouldn't be checked.
            if (expectedHtml === null) {
                continue;
            }

            assert.equal(
                actualHtml, expectedHtml,
                `Body row ${rowIndex+1}, cell ${cellIndex+1}`
                + ` should have expected content`,
            );
        }
    }
    else {
        // expectedRow is an Object, with entries for only the cell values
        // that are to be checked. Object keys are the column names.

        let columnNamesToIndices = {};
        for (let cellIndex = 0; cellIndex < columnNames.length; cellIndex++) {
            columnNamesToIndices[columnNames[cellIndex]] = cellIndex;
        }

        for (let [columnName, expectedHtml] of Object.entries(expectedRow)) {
            let cellIndex = columnNamesToIndices[columnName];
            let actualHtml = cellsContents[cellIndex];

            assert.equal(
                actualHtml, expectedHtml,
                `Body row ${rowIndex+1}, ${columnName} cell`
                + ` should have expected content`,
            );
        }
    }
}


QUnit.module("Preview", (hooks) => {
    hooks.beforeEach(() => {
        useFixture('main');
        UploadImagesHelper.init({
            uploadPreviewUrl: "preview_url",
            uploadStartUrl: "start_url",
        });
    });
    hooks.afterEach(() => {
        // Restore fetch() to its native implementation
        fetchMock.reset();
    });

    test("basics", async (assert) => {
        let imageFile = await makeImageFile('test_file.jpg');

        // Promises and resolvers help us control the order that
        // things will run in.
        let value = Promise.withResolvers();
        let prePreviewChecksPromise = value.promise;
        let prePreviewChecksResolver = value.resolve;

        // Mock preview request and response
        // https://www.wheresrhys.co.uk/fetch-mock/docs/legacy-api/API/Mocking/mock
        fetchMock.post(
            'preview_url',
            // Take request, return response
            async (url, request) => {
                let expectedFileInfo = JSON.stringify(
                    [{filename: 'test_file.jpg', size: 664}]
                );
                assert.equal(
                    request.body.get('file_info'), expectedFileInfo,
                    "Request's file info should be as expected");
                assert.equal(
                    Array.from(request.body.keys()).length, 1,
                    "Request shouldn't have unexpected params");
                assert.true(
                    request.headers.hasOwnProperty('X-CSRFToken'),
                    "Request should contain a CSRF token");
                assert.equal(
                    request.mode, 'same-origin',
                    "Request should be restricted to same origin");

                // Wait for other checks to run before responding
                await prePreviewChecksPromise;

                return {statuses: [{ok: true}]};
            },
        );

        setFiles([imageFile]);

        // Check state of the UI before the preview response

        assertStatusDisplay(assert, "Checking files...")
        let uploadStartButton = document.getElementById('id_upload_submit');
        assertButtonState(
            assert, uploadStartButton,
            {hidden: false, disabled: true, name: "Upload start"});
        let uploadAbortButton =
            document.getElementById('id_upload_abort_button');
        assertButtonState(
            assert, uploadAbortButton,
            {hidden: true, disabled: true, name: "Upload abort"});

        let filesTable = document.getElementById('files_table');
        let expectedContents = [
            [
                '<td>test_file.jpg</td>',
                '<td class="size_cell">664 B</td>',
                '<td class="status_cell"></td>',
            ],
        ]
        assertTableValues(assert, filesTable, expectedContents);

        let previewHandlerPromise = observePreviewHandler();
        // Let the preview run.
        prePreviewChecksResolver();
        // Wait for the preview and its response handler to run.
        await previewHandlerPromise;

        // Check state of the UI after the preview response

        assertStatusDisplay(assert, "Ready for upload");
        assertButtonState(
            assert, uploadStartButton,
            {hidden: false, disabled: false, name: "Upload start"});
        assertButtonState(
            assert, uploadAbortButton,
            {hidden: true, disabled: true, name: "Upload abort"});

        expectedContents = [
            [
                '<td>test_file.jpg</td>',
                '<td class="size_cell">664 B</td>',
                '<td class="status_cell">Ready</td>',
            ],
        ]
        assertTableValues(assert, filesTable, expectedContents);

        let preUploadSummary = document.getElementById('pre_upload_summary');
        assert.equal(
            preUploadSummary.textContent,
            "1 file(s) total"
            + "1 file(s) (664 B) can be uploaded",
            "Pre-upload summary should be as expected");
    });

    test("duplicate", (assert) => {
        // TODO
    });

    test("non-image", (assert) => {
        // TODO
    });

    test("mix", (assert) => {
        // TODO
    });

    test("replace selection", (assert) => {
        // TODO: test having more files, and test having less files, than previous selection
    });

    test("no files", (assert) => {
        // TODO
    });

    test("name prefix", (assert) => {
        // TODO
    });
});


QUnit.module("Upload", (hooks) => {
    hooks.beforeEach(() => {
        useFixture('main');
        UploadImagesHelper.init({
            uploadPreviewUrl: "preview_url",
            uploadStartUrl: "start_url",
        });
    });
    hooks.afterEach(() => {
        // Restore fetch() to its native implementation
        fetchMock.reset();
        window.confirm = originalWindowConfirm;
    });

    test("single", async (assert) => {
        let imageFile = await makeImageFile('test_file.jpg');

        fetchMock.post(
            'preview_url',
            (url, request) => {
                return {statuses: [{ok: true}]};
            },
        );

        let previewHandlerPromise = observePreviewHandler();
        setFiles([imageFile]);
        await previewHandlerPromise;

        let value = Promise.withResolvers();
        let preUploadChecksPromise = value.promise;
        let preUploadChecksResolver = value.resolve;

        // Mock upload request and response
        fetchMock.post(
            'start_url',
            // Take request, return response
            async (url, request) => {
                assert.equal(
                    request.body.get('file').size, 664,
                    "Request's file size should be as expected");
                assert.equal(
                    request.body.get('name'), 'test_file.jpg',
                    "Request's file name should be as expected");
                assert.equal(
                    Array.from(request.body.keys()).length, 2,
                    "Request shouldn't have unexpected params");
                assert.true(
                    request.headers.hasOwnProperty('X-CSRFToken'),
                    "Request should contain a CSRF token");
                assert.equal(
                    request.mode, 'same-origin',
                    "Request should be restricted to same origin");

                // Wait for other checks to run before responding
                await preUploadChecksPromise;

                return {
                    link: 'images/10/view',
                    image_id: 10,
                };
            },
        );

        let uploadStartButton = document.getElementById('id_upload_submit');
        uploadStartButton.dispatchEvent(new Event('click'));

        // Check state of the UI before the upload finishes

        let filesField = document.getElementById('id_files');
        assert.true(filesField.disabled, "Files field should be disabled");
        assertStatusDisplay(assert, "Uploading...");

        assertButtonState(
            assert, uploadStartButton,
            {hidden: true, disabled: true, name: "Upload start"});
        let uploadAbortButton =
            document.getElementById('id_upload_abort_button');
        assertButtonState(
            assert, uploadAbortButton,
            {hidden: false, disabled: false, name: "Upload abort"});

        let midUploadSummary = document.getElementById('mid_upload_summary');
        assert.equal(
            midUploadSummary.textContent,
            "Uploaded: 0 of 1 (0 B of 664 B, 0.0%)",
            "Upload summary should be as expected");

        let filesTable = document.getElementById('files_table');
        let expectedContents = [
            [
                '<td>test_file.jpg</td>',
                '<td class="size_cell">664 B</td>',
                '<td class="status_cell">Uploading...</td>',
            ],
        ]
        assertTableValues(assert, filesTable, expectedContents);

        let proceedLinksContainer = document.getElementById(
            'proceed-links-container');
        assert.true(
            proceedLinksContainer.hidden, "Proceed links should be hidden");

        let uploadHandlerPromise = observeUploadHandler(0);
        // Let the upload run.
        preUploadChecksResolver();
        // Wait for the upload and its response handler to run.
        await uploadHandlerPromise;

        // Check state of the UI after the upload finishes

        assertStatusDisplay(assert, "Upload complete");
        assertButtonState(
            assert, uploadStartButton,
            {hidden: true, disabled: true, name: "Upload start"});
        assertButtonState(
            assert, uploadAbortButton,
            {hidden: true, disabled: true, name: "Upload abort"});
        assert.equal(
            midUploadSummary.textContent,
            "Uploaded: 1 of 1 (664 B of 664 B, 100.0%)",
            "Upload summary should be as expected");

        expectedContents = [
            [
                '<td>test_file.jpg</td>',
                '<td class="size_cell">664 B</td>',
                '<td class="status_cell">'
                + '<a href="images/10/view" target="_blank">Uploaded</a></td>',
            ],
        ]
        assertTableValues(assert, filesTable, expectedContents);

        assert.false(
            proceedLinksContainer.hidden, "Proceed links should be shown");
        let manageMetadataLink = document.getElementById(
            'manage-metadata-link');
        assert.equal(
            manageMetadataLink.href,
            window.location.origin
            + '/source/1/browse/metadata/'
            + '?image_id_range=10_10',
            "Link for proceeding to edit metadata should be as expected")
    });

    test("multiple", (assert) => {
        // TODO
    });

    test("non-uploadable", (assert) => {
        // TODO
    });

    test("mix", (assert) => {
        // TODO
    });

    test("abort", async (assert) => {
        let imageFile = await makeImageFile('test_file.jpg');

        fetchMock.post(
            'preview_url',
            (url, request) => {
                return {statuses: [{ok: true}]};
            },
        );

        let previewHandlerPromise = observePreviewHandler();
        setFiles([imageFile]);
        await previewHandlerPromise;

        let value = Promise.withResolvers();
        let nonResolvingPromise = value.promise;

        fetchMock.post(
            'start_url',
            async (url, request) => {
                // Ensure the response has no chance of finishing before
                // we abort.
                await nonResolvingPromise;
            },
        );

        // Start upload
        let uploadStartButton = document.getElementById('id_upload_submit');
        uploadStartButton.dispatchEvent(new Event('click'));

        // Mock confirm() so it can run without interaction.
        window.confirm = () => {
            return true;
        };

        // Abort upload
        let uploadAbortButton =
            document.getElementById('id_upload_abort_button');
        uploadAbortButton.dispatchEvent(new Event('click'));

        // Check state of the UI after aborting

        assertStatusDisplay(assert, "Upload aborted");
        assertButtonState(
            assert, uploadStartButton,
            {hidden: true, disabled: true, name: "Upload start"});
        assertButtonState(
            assert, uploadAbortButton,
            {hidden: true, disabled: true, name: "Upload abort"});
        let midUploadSummary = document.getElementById('mid_upload_summary');
        assert.equal(
            midUploadSummary.textContent,
            "Uploaded: 0 of 1 (0 B of 664 B, 0.0%)",
            "Upload summary should be as expected");

        let filesTable = document.getElementById('files_table');
        let expectedContents = [
            [
                '<td>test_file.jpg</td>',
                '<td class="size_cell">664 B</td>',
                '<td class="status_cell">Uploading...</td>',
            ],
        ]
        assertTableValues(assert, filesTable, expectedContents);

        let proceedLinksContainer = document.getElementById(
            'proceed-links-container');
        assert.true(
            proceedLinksContainer.hidden, "Proceed links should be hidden");
    });
});
