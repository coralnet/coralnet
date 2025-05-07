class BrowseActionHelper {

    constructor(pageImageIds) {
        this.pageImageIds = pageImageIds;

        this.actionBox = document.getElementById('action-box');
        this.actionForms = this.actionBox.querySelectorAll('form');

        // Grab select fields and add handlers.
        this.actionSelectField =
            this.actionBox.querySelector('select[name=browse_action]');
        this.actionSelectField.addEventListener(
            'change', this.onActionChange.bind(this));
        this.imageSelectTypeField =
            this.actionBox.querySelector('select[name=image_select_type]');
        this.imageSelectTypeField.addEventListener(
            'change', this.onActionChange.bind(this));

        // Add submit handlers.
        this.actionForms.forEach((form) => {
            form.addEventListener(
                'submit', this.actionSubmit.bind(this));
        });

        // Initialize action-related states.
        this.onActionChange();
    }

    onActionChange() {
        let action = this.actionSelectField.value;
        let imageSelectType = this.imageSelectTypeField.value;

        // Show only the relevant action form
        this.actionForms.forEach((form) => {
            form.hidden = true;
        });

        // Set defaults for these form-specific variables
        let formId = null;
        this.isAjax = false;
        this.actionAfterAjax = null;
        this.confirmMessage = null;
        this.confirmInput = null;
        this.actionSubmitButton = null;

        if (action === '') {
            return;
        }
        else if (action === 'annotate' && imageSelectType === 'all') {
            formId = 'annotate-all-form';
        }
        else if (action === 'annotate' && imageSelectType === 'selected') {
            formId = 'annotate-selected-form';
        }
        else if (action === 'export_metadata') {
            formId = 'export-metadata-form';
        }
        else if (action === 'export_annotations') {
            formId = 'export-annotations-prep-form';
            this.isAjax = true;
            this.actionAfterAjax = this.serveExport.bind(this);
        }
        else if (action === 'export_annotations_cpc') {
            formId = 'export-annotations-cpc-prep-form';
            this.isAjax = true;
            this.actionAfterAjax = this.serveExport.bind(this);
        }
        else if (action === 'export_image_covers') {
            formId = 'export-image-covers-prep-form';
            this.isAjax = true;
            this.actionAfterAjax = this.serveExport.bind(this);
        }
        else if (action === 'export_calcify_rates') {
            formId = 'export-calcify-rates-prep-form';
            this.isAjax = true;
            this.actionAfterAjax = this.serveExport.bind(this);
        }
        else if (action === 'delete_images') {
            formId = 'delete-images-ajax-form';
            this.isAjax = true;
            this.actionAfterAjax = this.refetchBrowse.bind(this);
            this.confirmMessage =
                "Are you sure you want to delete these images?" +
                " You won't be able to undo this." +
                " Type \"delete\" if you're sure.";
            this.confirmInput = "delete";
        }
        else if (action === 'delete_annotations') {
            formId = 'delete-annotations-ajax-form';
            this.isAjax = true;
            this.actionAfterAjax = this.refetchBrowse.bind(this);
            this.confirmMessage =
                "Are you sure you want to delete the annotations" +
                " for these images? You won't be able to undo this." +
                " Type \"delete\" if you're sure.";
            this.confirmInput = "delete";
        }

        this.currentActionForm = document.getElementById(formId);
        this.currentActionForm.hidden = false;
        this.actionSubmitButton =
            this.currentActionForm.querySelector('button.submit');
    }

    addImageSelectFields() {
        let imageSelectFieldContainer =
            this.currentActionForm.querySelector(
                '.image-select-field-container');

        // Create this container if it doesn't already exist in the form.
        if (!imageSelectFieldContainer) {
            imageSelectFieldContainer = document.createElement('span');
            imageSelectFieldContainer.className =
                'image-select-field-container';
            this.currentActionForm.appendChild(imageSelectFieldContainer);
        }

        // Clear image select fields from any previous submit attempts.
        imageSelectFieldContainer.replaceChildren();

        let imageSelectType = this.imageSelectTypeField.value;

        let imageSelectArgs = {};
        if (imageSelectType === 'all') {
            // Get search params
            document.getElementById('previous-image-form-fields')
                .querySelectorAll('input').forEach((input) => {
                    imageSelectArgs[input.name] = input.value;
                });
        }
        else if (imageSelectType === 'selected') {
            // Get image IDs
            imageSelectArgs['image_form_type'] = 'ids';
            imageSelectArgs['ids'] = this.pageImageIds.toString();
        }

        for (let fieldName in imageSelectArgs) {
            let value = imageSelectArgs[fieldName];

            // Add as hidden fields because the user doesn't have to
            // interact with them.
            let field = document.createElement('input');
            field.hidden = true;
            field.name = fieldName;
            field.value = value;
            imageSelectFieldContainer.appendChild(field);
        }
    }

    actionSubmit(event) {
        // We'll decide when and whether to submit the form.
        event.preventDefault();

        if (this.confirmMessage) {
            if (!this.confirmAction(this.confirmMessage, this.confirmInput)) {
                return;
            }
        }

        // Image-select fields must be passed differently according to
        // the user's chosen image select type (all images, or only
        // selected images). We implement this by adding the fields to the
        // relevant action form via Javascript, here in the submit button
        // handler.
        this.addImageSelectFields();

        if (this.isAjax) {
            // This action has an ajax submit to the
            // form's URL, and then possibly more steps after that.

            // Disable the button to prevent double
            // submission, and let the user know the ajax request is going.
            // We also disable the action field to prevent confusing behavior.
            this.actionSubmitButton.disabled = true;
            this.actionSubmitButton.textContent = "Working...";
            this.actionSelectField.disabled = true;

            let promise = util.fetch(
                this.currentActionForm.action,
                {method: 'POST', body: new FormData(this.currentActionForm)},
                this.ajaxActionCallback.bind(this));

            // TODO: Update this once our Selenium tests are runnable again
            window.seleniumDebugDeleteTriggered = true;
            return promise;
        }
        else {
            // This action has a non-ajax submit
            // to the form's URL.
            this.currentActionForm.submit();
        }
    }

    confirmAction(message, requiredInput) {
        if (requiredInput) {
            // Require the user to type a specific string in the prompt field
            // in order to confirm the action.
            let userInput = window.prompt(message);
            return (userInput === requiredInput);
        }
        else {
            // Simple yes/no confirmation.
            return window.confirm(message);
        }
    }

    ajaxActionCallback(response) {
        if (response['error']) {
            // Response is OK, but there's an error message in the JSON.
            // TODO: Can we do better than an alert? Consider displaying the
            // error on the action form's layout instead.
            alert("Error: " + response['error']);
        }
        else if (this.actionAfterAjax) {
            this.actionAfterAjax(response);
        }

        this.actionSubmitButton.disabled = false;
        this.actionSubmitButton.textContent = "Go";
        this.actionSelectField.disabled = false;
    }

    serveExport(prepResponse) {
        // Submit the download form, passing in the session key
        // from the export-prep Ajax response.
        let downloadForm = document.getElementById('export-serve-form');
        let sessionDataTimeField = downloadForm.querySelector(
            'input[name="session_data_timestamp"]');
        sessionDataTimeField.value = prepResponse.session_data_timestamp;
        downloadForm.submit();
    }

    refetchBrowse() {
        // Re-fetch the current browse page, including the search/filter fields
        // that got us the current set of images, and the current page number.
        //
        // assign(), unlike reload(), places your scroll position at the
        // top of the page instead of where you previously were, which is
        // good because the deletion notice should be at the top.
        window.location.assign(window.location);
    }
}
