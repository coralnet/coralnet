class BrowseSearchHelper {

    static setupSearchSubmitLogic(form) {
        let boundMethod = BrowseSearchHelper.onSearchSubmit.bind(
            BrowseSearchHelper, form);
        form.addEventListener('submit', boundMethod);
    }

    static onSearchSubmit(form) {
        // Disable any blank fields so that they don't get submitted and
        // don't clutter up the URL params.
        let hasAnyFieldEnabled = false;
        form.querySelectorAll('input, select').forEach((field) => {
            if (field.type === 'submit') {
                // Submit button isn't a field.
                return;
            }

            if (field.value === '') {
                field.disabled = true;
            }
            else {
                hasAnyFieldEnabled = true;
            }
        });

        // But make sure there's at least one field to submit, since
        // sometimes the server wants to be able to tell if a search was
        // submitted or not.
        if (!hasAnyFieldEnabled) {
            let extraField = document.createElement('input');
            extraField.type = 'hidden';
            extraField.name = 'search';
            extraField.value = 'true';
            form.appendChild(extraField);
        }

        // Then after returning from here, the default submit behavior
        // should run, which is submitting the form to the server.
    }
}

export default BrowseSearchHelper;
