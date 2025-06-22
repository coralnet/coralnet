/* The following "singleton" design pattern is from
 * http://stackoverflow.com/a/1479341/
 */
var UploadAnnotationsCPCHelper = (function() {

    var $statusDisplay = null;
    var $statusDetail = null;
    var $previewTable = null;
    var $previewTableContainer = null;

    var $cpcForm = null;
    var cpcFileField = null;
    var cpcFileError = null;
    var previewTableContent = null;
    var previewDetails = null;

    var $uploadStartButton = null;

    var uploadPreviewUrl = null;
    var uploadStartUrl = null;
    var maxFiles = null;


    function updateStatus(newStatus) {
        var messageLines;
        var i;

        $statusDisplay.empty();

        // Update the upload start button.
        if (newStatus === 'no_file') {
            $uploadStartButton.disable();
            $statusDisplay.text("CPC files not selected yet");
            $statusDetail.empty();
        }
        else if (newStatus === 'processing') {
            $uploadStartButton.disable();
            $statusDisplay.text("Processing CPC files...");
            $statusDetail.empty();
        }
        else if (newStatus === 'preview_error') {
            $uploadStartButton.disable();
            $statusDisplay.text("Error reading CPC files");
            $statusDetail.empty();

            // Fill $statusDetail with the error message,
            // which may span multiple lines
            messageLines = cpcFileError.split('\n');
            for (i = 0; i < messageLines.length; i++) {
                $statusDetail.append(messageLines[i]);

                if (i < messageLines.length-1) {
                    $statusDetail.append($('<br>'));
                }
            }
        }
        else if (newStatus === 'ready') {
            $uploadStartButton.enable();
            $statusDisplay.text(
                "Data OK; confirm below and click" +
                " 'Save points and annotations'");

            $statusDetail.empty();
            $statusDetail.append(
                "Found data for {0} images".format(
                    previewDetails['numImages']),
                $('<br>'),
                "Total of {0} points and {1} annotations".format(
                    previewDetails['totalPoints'],
                    previewDetails['totalAnnotations'])
            );

            var numImagesWithExistingAnnotations =
                Number(previewDetails['numImagesWithExistingAnnotations']);
            if (numImagesWithExistingAnnotations > 0) {
                $statusDetail.append(
                    $('<br>'),
                    $('<span class="annotation-delete-info">').append((
                        "{0} images have existing annotations" +
                        " that will be deleted").format(
                            numImagesWithExistingAnnotations))
                );
            }
        }
        else if (newStatus === 'saving') {
            $uploadStartButton.disable();
            $statusDisplay.text("Saving points and annotations...");
            // Retain previous status detail
        }
        else if (newStatus === 'save_error') {
            $uploadStartButton.disable();
            $statusDisplay.text("Error while saving; no points or annotations saved");
            $statusDetail.empty();

            // Fill $statusDetail with the error message,
            // which may span multiple lines
            messageLines = cpcFileError.split('\n');
            for (i = 0; i < messageLines.length; i++) {
                $statusDetail.append(messageLines[i]);

                if (i < messageLines.length-1) {
                    $statusDetail.append($('<br>'));
                }
            }
        }
        else if (newStatus === 'saved') {
            $uploadStartButton.disable();
            $statusDisplay.text("Points and annotations saved");
            // Retain previous status detail
        }
        else {
            // This should only happen if we don't keep the status strings
            // synced between status get / status set code.
            alert(
                "Error - Invalid status: {0}".format(newStatus) +
                "\nIf the problem persists, please let us know on the forum."
            );
        }
    }

    function updatePreviewTable() {
        $previewTable.empty();

        if (previewTableContent === null) {
            return;
        }

        // One row for each image specified in the CPCs
        var i;
        for (i = 0; i < previewTableContent.length; i++) {
            var contentForImage = previewTableContent[i];
            var $row = $('<tr>');

            $row.append(
                $('<td>').append(
                    $('<a>').append(
                        contentForImage['name']
                    ).attr(
                        'href', contentForImage['link']
                    ).attr(
                        'target', '_blank'
                    )
                )
            );

            var $cell2 = $('<td>').append(
                contentForImage['createInfo']
            );
            if (contentForImage.hasOwnProperty('deleteInfo')) {
                $cell2.append(
                    $('<br>'),
                    $('<span class="annotation-delete-info">').append(
                        contentForImage['deleteInfo']
                    )
                );
            }
            $row.append($cell2);

            $previewTable.append($row);
        }
    }

    function updateUploadPreview() {
        previewTableContent = null;

        if (cpcFileField.files.length === 0) {
            // No CPC file.
            updateStatus('no_file');
            updatePreviewTable();
            return;
        }
        if (cpcFileField.files.length > maxFiles) {
            cpcFileError =
                `Can't upload more than ${maxFiles} files at a time.`;
            updateStatus('preview_error');
            updatePreviewTable();
            return;
        }

        updateStatus('processing');
        updatePreviewTable();

        $.ajax({
            // URL to make request to
            url: uploadPreviewUrl,
            // Data to send in the request
            // https://developer.mozilla.org/en-US/docs/Web/API/FormData/Using_FormData_Objects
            data: new FormData($cpcForm[0]),
            // Don't let jQuery auto-set the Content-Type header
            // if we're using FormData
            // http://stackoverflow.com/a/5976031/
            contentType: false,
            // Don't let jQuery attempt to convert the FormData
            // to a string, as it will fail
            // http://stackoverflow.com/a/5976031/
            processData: false,
            type: 'POST',
            // Callbacks
            success: handleUploadPreviewResponse,
            error: util.handleServerError
        });
    }

    function handleUploadPreviewResponse(response) {
        if (response['error']) {
            cpcFileError = response['error'];
            updateStatus('preview_error');
        }
        else {
            previewTableContent = response['previewTable'];
            previewDetails = response['previewDetails'];
            updateStatus('ready');
        }
        updatePreviewTable();
    }

    function startUpload() {
        if (Number(previewDetails['numImagesWithExistingAnnotations']) > 0) {
            var confirmResult = window.confirm(
                "Some existing annotations will be replaced. Are you sure?");
            if (!confirmResult) {
                return;
            }
        }

        updateStatus('saving');

        // Warn the user if they're trying to
        // leave the page during the save.
        util.pageLeaveWarningEnable(
            "Points/annotations are still being saved.");

        // Start the upload.
        $.ajax({
            // URL to make request to
            url: uploadStartUrl,
            type: 'POST',
            // Callbacks
            success: handleUploadResponse,
            error: util.handleServerError
        });
    }

    /* Callback after the Ajax response is received, indicating that
     * the server upload and processing are done. */
    function handleUploadResponse(response) {
        if (response['error']) {
            updateStatus('save_error');
            cpcFileError = response['error'];
        }
        else {
            updateStatus('saved');
        }

        util.pageLeaveWarningDisable();
    }


    /* Public methods.
     * These are the only methods that need to be referred to as
     * UploadAnnotationsHelper.methodname. */
    return {

        /* Initialize the upload form. */
        initForm: function(params){

            // Get the parameters.
            uploadPreviewUrl = params['uploadPreviewUrl'];
            uploadStartUrl = params['uploadStartUrl'];
            maxFiles = params['maxFiles'];

            // Upload status elements.
            $statusDisplay = $('#status_display');
            $statusDetail = $('#status_detail');

            // Preview table.
            $previewTable = $('table#preview_table');
            // And its container element.
            $previewTableContainer = $('#preview_table_container');

            // Form and field elements.
            $cpcForm = $('#cpc_form');
            cpcFileField = $('#id_cpc_files')[0];
            let $labelMappingRadioChoices = $(
                'input[type=radio][name=label_mapping]');

            // Button elements.
            $uploadStartButton = $('#id_upload_submit');


            // Handlers.
            $(cpcFileField).change(function() {
                updateUploadPreview();
            });
            $labelMappingRadioChoices.change(function() {
                updateUploadPreview();
            });
            $uploadStartButton.click(function() {
                startUpload();
            });

            // Initialize the page properly regardless of whether
            // we load the page straight (no files initially) or
            // refresh the page (browser may keep previous file field value).
            updateUploadPreview();
        }
    }
})();
