class CalcifyTablesHelper {

    constructor(canManageTables) {

        // Show calcify table management dialog when the appropriate button
        // is clicked.
        document.getElementById('manage-calcify-tables-button')
                .addEventListener('click', function () {
            $('#manage-calcify-tables').dialog({
                width: 800,
                height: 500,
                modal: true,
                title: "Calcification rate tables"
            });
        });

        if (!canManageTables) {
            return;
        }
        // All of the below assumes permission to upload/delete tables.

        this.uploadFormE = document.getElementById(
            'new-rate-table-form');
        this.uploadFormStatusE = document.getElementById(
            'new-rate-table-form-status');
        this.uploadSubmitEnabled = true;

        // Show calcify table upload dialog when the appropriate button
        // is clicked.
        document.getElementById('new-rate-table-form-show-button')
                .addEventListener('click', function () {
            $('#new-rate-table-form-popup').dialog({
                width: 500,
                height: 300,
                modal: true,
                title: "Upload a custom rate table",
                // This option adds an extra CSS class to the dialog.
                // https://api.jqueryui.com/dialog/#option-classes
                classes: {
                    'ui-dialog': 'ui-dialog-form'
                }
            });
        });

        // Upload form submit handler.
        // bind() ensures `this` refers to our class instance, not the element.
        // https://stackoverflow.com/a/43727582
        this.uploadFormE.onsubmit = this.uploadSubmit.bind(this);

        // Delete forms' submit handlers.
        this.setDeleteFormHandlers();
    }

    uploadSubmit(event) {
        // Don't let the form do a non-Ajax submit
        // (browsers' default submit behavior).
        event.preventDefault();

        if (this.uploadSubmitEnabled) {
            let url = this.uploadFormE.action;
            let formData = new FormData(this.uploadFormE);

            util.fetch(
                url, {method: 'POST', body: formData},
                this.uploadHandleResponse.bind(this));

            this.uploadFormStatusE.textContent = "Submitting...";
            this.uploadSubmitEnabled = false;
        }
    }

    uploadHandleResponse(response) {
        this.uploadFormStatusE.textContent = "";
        this.uploadSubmitEnabled = true;

        if (response['error']) {
            // There was an error processing the form submission.
            this.uploadFormStatusE.textContent = response['error'];
            return;
        }

        this.refreshTableChoices(response);

        this.uploadFormStatusE.textContent = "Table successfully uploaded.";

        // Clear the form fields in case the user wants to upload another table
        let formFields = this.uploadFormE.querySelectorAll(
            'input[type="text"], input[type="file"], textarea');
        formFields.forEach(function(field) {
            field.value = '';
        });
    }

    deleteSubmit(form, event) {
        // Don't let the form do a non-Ajax submit
        // (browsers' default submit behavior).
        event.preventDefault();

        let confirmResult = window.confirm(
            "Are you sure you want to delete this rate table?");
        if (!confirmResult) {
            return;
        }

        let url = form.action;
        // Form data includes the CSRF token, which we need.
        let formData = new FormData(form);

        util.fetch(
            url, {method: 'POST', body: formData},
            this.refreshTableChoices.bind(this));
    }

    /*
    This should be called when handling a response which changes the
    source's available tables. So, a response from upload or delete.
    `response` is the response JSON from either of those views.
    */
    refreshTableChoices(response) {
        // Replace HTML for the table dropdown.
        let element = document.getElementById('id_rate_table_id');
        element.insertAdjacentHTML('afterend', response['tableDropdownHtml']);
        element.remove();

        // Replace HTML for the grid of tables element.
        element = document.getElementById('table-of-calcify-tables');
        element.insertAdjacentHTML('afterend', response['gridOfTablesHtml']);
        element.remove();

        // Now that the delete forms have been replaced, attach
        // the delete handlers to the new forms.
        this.setDeleteFormHandlers();
    }

    setDeleteFormHandlers() {
        let deleteForms = document.querySelectorAll('form.rate-table-delete');
        deleteForms.forEach((deleteForm) => {
            deleteForm.onsubmit = this.deleteSubmit.bind(this, deleteForm);
        });
    }
}

export default CalcifyTablesHelper;
