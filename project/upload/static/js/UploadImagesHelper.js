/* The following "singleton" design pattern is from
 * http://stackoverflow.com/a/1479341/
 */
var UploadImagesHelper = (function() {

    var $statusDisplay = null;
    var $preUploadSummary = null;
    var $midUploadSummary = null;
    var $filesTable = null;
    var $filesTableContainer = null;
    var $filesTableAutoScrollCheckbox = null;
    var $filesTableAutoScrollCheckboxContainer = null;

    var filesField = null;
    var namePrefixField = null;

    var $uploadStartButton = null;
    var $uploadAbortButton = null;
    var proceedLinksContainer = null;
    var manageMetadataLink = null;

    var uploadPreviewUrl = null;
    var uploadStartUrl = null;
    var csrfToken = null;

    var files = [];
    var numErrors = 0;
    var numUploadables = 0;
    var uploadableTotalSize = 0;

    var numUploaded = 0;
    var numUploadSuccesses = 0;
    var numUploadErrors = 0;
    var uploadedTotalSize = 0;
    var uploadedImageIds = null;

    var currentFileIndex = null;
    var abortController = null;
    var abortSignal = null;


    /**
    Makes cssClass the only style class of a particular row (tr element)
    of the files table.
    Pass in '' as the cssClass to just remove the style.

    Assumes we only need up to 1 style on any row at any given time.
    If that assumption is no longer valid, then this function should be
    changed.
    */
    function styleFilesTableRow(rowIndex, cssClass) {
        files[rowIndex].$tableRow.attr('class', cssClass);
    }

    function updateStatus(newStatus) {
        $statusDisplay.empty();

        // Hide and disable both buttons by default. In each case below,
        // specify only what's shown and enabled.
        $uploadStartButton.hide();
        $uploadStartButton.disable();
        $uploadAbortButton.hide();
        $uploadAbortButton.disable();

        if (newStatus === 'no_files') {
            $uploadStartButton.show();
            $statusDisplay.text("No image files selected yet");
        }
        else if (newStatus === 'checking') {
            $uploadStartButton.show();
            $statusDisplay.text("Checking files...");
        }
        else if (newStatus === 'no_uploadables') {
            $uploadStartButton.show();
            $statusDisplay.text("Cannot upload any of these image files");
        }
        else if (newStatus === 'ready') {
            $uploadStartButton.show();
            $uploadStartButton.enable();
            $statusDisplay.text("Ready for upload");
        }
        else if (newStatus === 'uploading') {
            $uploadAbortButton.show();
            $uploadAbortButton.enable();
            $statusDisplay.text("Uploading...");
        }
        else if (newStatus === 'uploaded') {
            $statusDisplay.text("Upload complete");
        }
        else if (newStatus === 'aborted') {
            $statusDisplay.text("Upload aborted");
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

    /* Get the file details and display them in the table. */
    function updateFiles() {

        // Clear the table rows
        files.forEach(function(f) {
            f.$tableRow.remove();
        });
        // Clear the file array
        files.length = 0;

        // No need to do anything more if there are no files anyway.
        if (filesField.files.length === 0) {
            updateStatus('no_files');
            return;
        }

        updateStatus('checking');

        // Re-build the file array.
        // Set the image files as files[0].file, files[1].file, etc.
        Array.prototype.forEach.call(filesField.files, function(f) {
            files.push({'file': f});
        });

        var namePrefix = namePrefixField.value;

        // Make a table row for each file
        files.forEach(function(f) {

            // Create a table row containing file details
            var $filesTableRow = $("<tr>");

            // Filename, filesize
            $filesTableRow.append($("<td>").text(namePrefix + f.file.name));

            var $sizeCell = $("<td>");
            $sizeCell.addClass('size_cell');
            $sizeCell.text(util.filesizeDisplay(f.file.size));
            $filesTableRow.append($sizeCell);

            // Filename status, to be filled in with an Ajax response
            var $statusCell = $("<td>");
            $statusCell.addClass('status_cell');
            $filesTableRow.append($statusCell);
            f.$statusCell = $statusCell;

            // Add the row to the table
            $filesTable.append($filesTableRow);
            f.$tableRow = $filesTableRow;
        });

        // Initialize upload statuses to null
        files.forEach(function(f) {
            f.status = null;
        });

        var fileInfoForPreviewQuery = [];
        files.forEach(function(f) {
            fileInfoForPreviewQuery.push({
                filename: namePrefix + f.file.name,
                size: f.file.size
            });
        });

        // https://developer.mozilla.org/en-US/docs/Web/API/FormData/Using_FormData_Objects
        var formData = new FormData();
        formData.append('file_info', JSON.stringify(fileInfoForPreviewQuery));

        // Update upload statuses based on the server's info
        util.fetch(
            uploadPreviewUrl,
            {
                method: 'POST',
                body: formData,
            },
            handleUploadPreviewResponse,
            {csrfToken: csrfToken},
        );
    }

    function handleUploadPreviewResponse(response) {
        var statuses = response['statuses'];
        numErrors = 0;
        numUploadables = 0;
        uploadableTotalSize = 0;

        // Update table's status cells
        var i;
        for (i = 0; i < statuses.length; i++) {

            var fileStatus = statuses[i];

            var $statusCell = files[i].$statusCell;
            $statusCell.empty();

            if (fileStatus.hasOwnProperty('error')) {

                if (fileStatus.hasOwnProperty('link')) {
                    $statusCell.append(
                        $("<a>")
                            .text(fileStatus['error'])
                            .attr('href', fileStatus['link'])
                            // Open in new window
                            .attr('target', '_blank')
                    );
                }
                else {
                    $statusCell.text(fileStatus['error']);
                }

                files[i].status = 'error';
                files[i].isUploadable = false;
                numErrors += 1;
                styleFilesTableRow(i, 'preupload_error');
            }
            else {
                $statusCell.text("Ready");

                files[i].status = 'ok';
                files[i].isUploadable = true;
                numUploadables += 1;
                uploadableTotalSize += files[i].file.size;
                styleFilesTableRow(i, '');
            }
        }

        // Update summary above table
        $preUploadSummary.empty();

        var $summaryList = $('<ul>');
        $summaryList.append(
            $('<li>').append(
                $('<strong>').text(
                    "{0} file(s) ({1}) can be uploaded".format(
                        numUploadables,
                        util.filesizeDisplay(uploadableTotalSize)
                    )
                )
            )
        );
        if (numErrors > 0) {
            $summaryList.append(
                $('<li>').text(
                    "{0} file(s) can't be uploaded".format(
                        numErrors
                    )
                )
            );
        }
        $preUploadSummary.append(
            "{0} file(s) total".format(files.length),
            $summaryList
        );

        if (numUploadables <= 0) {
            updateStatus('no_uploadables');
        }
        else {
            updateStatus('ready');
        }

        // Show or hide the files table auto-scroll option
        // depending on whether the table is tall enough to need a scrollbar.
        if ($filesTableContainer[0].scrollHeight >
            $filesTableContainer[0].clientHeight) {
            // There is overflow in the files table container, such that
            // it has a scrollbar.
            $filesTableAutoScrollCheckboxContainer.show();
        }
        else {
            // No scrollbar.
            $filesTableAutoScrollCheckboxContainer.hide();
        }
    }

    function startUpload() {
        // Disable all form fields and buttons on the page.
        $(filesField).prop('disabled', true);

        // Initialize the upload progress stats.
        numUploaded = 0;
        numUploadSuccesses = 0;
        numUploadErrors = 0;
        uploadedTotalSize = 0;
        updateMidUploadSummary();

        uploadedImageIds = [];

        // Warn the user if they're trying to
        // leave the page during the upload.
        util.pageLeaveWarningEnable("The upload is still going.");

        updateStatus('uploading');

        // Finally, upload the first file.
        currentFileIndex = 0;
        uploadFile();
    }

    /* Callback after one image's upload and processing are done. */
    function handleUploadResponse(response) {

        // Update the table with the upload status from the server.
        var $statusCell = files[currentFileIndex].$statusCell;
        $statusCell.empty();

        if (response.hasOwnProperty('error')) {
            $statusCell.text(response['error']);
            styleFilesTableRow(currentFileIndex, 'upload_error');
            numUploadErrors++;
        }
        else {
            $statusCell.append(
                $("<a>")
                    .text("Uploaded")
                    .attr('href', response['link'])
                    // Open in new window
                    .attr('target', '_blank')
            );
            styleFilesTableRow(currentFileIndex, 'uploaded');
            numUploadSuccesses++;
            uploadedImageIds.push(response['image_id']);
        }
        numUploaded++;
        uploadedTotalSize += files[currentFileIndex].file.size;

        updateMidUploadSummary();

        // Find the next file to upload, if any, and upload it.
        currentFileIndex++;
        uploadFile();
    }

    /* Find a file to upload, starting from the current currentFileIndex.
     * If the current file is not uploadable, increment the currentFileIndex
     * and try the next file.  Once an uploadable file is found, begin
     * uploading that file. */
    function uploadFile() {
        while (currentFileIndex < files.length) {

            if (files[currentFileIndex].isUploadable) {
                // An uploadable file was found, so upload it.

                var formData = new FormData();
                // Add the file as 'file' so that it can be validated
                // on the server side with a form field named 'file'.
                formData.append('file', files[currentFileIndex].file);
                // Add the name with prefix.
                formData.append(
                    'name',
                    namePrefixField.value + files[currentFileIndex].file.name);

                abortController = new AbortController();
                abortSignal = abortController.signal;
                util.fetch(
                    uploadStartUrl,
                    {
                        method: 'POST',
                        body: formData,
                        signal: abortSignal,
                    },
                    // Using fetch's returned Promise instead of this callback
                    // parameter, because not sure how to catch an AbortError
                    // with the latter.
                    handleUploadResponse,
                    {
                        csrfToken: csrfToken,
                        errorHandler: (err) => {
                            if (err.name !== 'AbortError') {
                                throw err;
                            }
                            // Else, it's an AbortError, and that case is already
                            // handled right after the code that does the abort.
                        }
                    },
                );

                // In the files table, update the status for that file.
                var $statusCell = files[currentFileIndex].$statusCell;
                $statusCell.empty();
                styleFilesTableRow(currentFileIndex, 'uploading');
                $statusCell.text("Uploading...");

                if ($filesTableAutoScrollCheckbox.prop('checked')) {
                    // Scroll the upload table's window to the file
                    // that's being uploaded.
                    // Specifically, scroll the file to the
                    // middle of the table view.
                    var scrollRowToTop = files[currentFileIndex].$tableRow[0].offsetTop;
                    var tableContainerHalfMaxHeight = parseInt($filesTableContainer.css('max-height')) / 2;
                    var scrollRowToMiddle = Math.max(scrollRowToTop - tableContainerHalfMaxHeight, 0);
                    $filesTableContainer.scrollTop(scrollRowToMiddle);
                }

                return;
            }

            // No uploadable file was found yet; keep looking.
            currentFileIndex++;
        }

        // If we got here, we've reached the end of the files array, so
        // there's nothing more to upload.
        updateStatus('uploaded');
        postUploadCleanup();

        // Update the proceed-to-manage-metadata link with a filter arg
        // that filters to the images that were just uploaded.
        var minUploadedImageId = Math.min(...uploadedImageIds);
        var maxUploadedImageId = Math.max(...uploadedImageIds);
        var searchParams = new URLSearchParams({
            image_id_range: `${minUploadedImageId}_${maxUploadedImageId}`,
        });
        manageMetadataLink.href += '?' + searchParams.toString();

        // Show the buttons for the user's next step.
        proceedLinksContainer.hidden = false;
    }

    function postUploadCleanup() {
        abortController = null;
        abortSignal = null;
        util.pageLeaveWarningDisable();
    }

    function updateMidUploadSummary() {
        $midUploadSummary.empty();

        var summaryTextLines = [];

        summaryTextLines.push($('<strong>').text("Uploaded: {0} of {1} ({2} of {3}, {4}%)".format(
            numUploaded,
            numUploadables,
            util.filesizeDisplay(uploadedTotalSize),
            util.filesizeDisplay(uploadableTotalSize),
            ((uploadedTotalSize/uploadableTotalSize)*100).toFixed(1)  // Percentage with 1 decimal place
        )));

        if (numUploadErrors > 0) {
            summaryTextLines.push("Upload successes: {0} of {1}".format(numUploadSuccesses, numUploaded));
            summaryTextLines.push("Upload errors: {0} of {1}".format(numUploadErrors, numUploaded));
        }

        var i;
        for (i = 0; i < summaryTextLines.length; i++) {
            // If not the first line, append a <br> first.
            // That way, the lines are separated by linebreaks.
            if (i > 0) {
                $midUploadSummary.append('<br>');
            }

            $midUploadSummary.append(summaryTextLines[i]);
        }
    }

    /**
    Abort the Ajax upload.

    - Depending on the timing of clicking Abort, a file may finish
    uploading and proceed with processing on the server, without a result
    being received by the client. This is probably undesired behavior,
    but there's not much that can be done about this.

    - There should be no concurrency issues, because Javascript is single
    threaded, and event handling code is guaranteed to complete before the
    invocation of an AJAX callback or a later event's callback. At least
    in the absence of Web Workers.
    http://stackoverflow.com/questions/9999056/
    */
    function abortUpload() {
        var confirmation = window.confirm(
            "Are you sure you want to abort the upload?");

        if (confirmation) {
            abortController.abort();
            updateStatus('aborted');
            postUploadCleanup();
        }
    }


    /* Public methods.
     * These are the only methods that need to be referred to as
     * UploadImagesHelper.methodname. */
    return {

        /* Initialize the page. */
        init: function(params){

            // Get the parameters.
            uploadPreviewUrl = params['uploadPreviewUrl'];
            uploadStartUrl = params['uploadStartUrl'];

            csrfToken =
                document.querySelector('[name=csrfmiddlewaretoken]').value;

            // Upload status summary elements.
            $preUploadSummary = $('#pre_upload_summary');
            $midUploadSummary = $('#mid_upload_summary');

            // The upload file table.
            $filesTable = $('table#files_table');
            // And its container element.
            $filesTableContainer = $('#files_table_container');
            // The checkbox to enable/disable auto-scrolling
            // of the files table.
            $filesTableAutoScrollCheckbox = $('input#files_table_auto_scroll_checkbox');
            // And its container element.
            $filesTableAutoScrollCheckboxContainer = $('#files_table_auto_scroll_checkbox_container');

            // Field elements.
            filesField = document.getElementById('id_files');
            namePrefixField = document.getElementById('id_name_prefix');

            // Button elements.
            $uploadStartButton = $('#id_upload_submit');
            $uploadAbortButton = $('#id_upload_abort_button');
            proceedLinksContainer = document.getElementById(
                'proceed-links-container');
            manageMetadataLink = document.getElementById(
                'manage-metadata-link');

            $statusDisplay = $('#status_display');


            // Hide the after-upload buttons for now
            proceedLinksContainer.hidden = true;

            // Handlers.
            $(filesField).change( function(){
                updateFiles();
            });
            $(namePrefixField).change( function(){
                updateFiles();
            });
            $uploadStartButton.click(startUpload);
            $uploadAbortButton.click(abortUpload);

            // Initialize the page properly regardless of whether
            // we load the page straight (empty fields initially) or
            // refresh the page (browser may keep previous field values).
            updateFiles();
        }
    }
})();
