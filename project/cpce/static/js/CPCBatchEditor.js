class CPCBatchEditor {

    cpcs = [];

    constructor(maxCpcFiles) {
        this.maxCpcFiles = maxCpcFiles;

        this.cpcDropZone.addEventListener('dragover', (event) => {
            // Prevent navigation.
            event.preventDefault();
        });
        this.cpcDropZone.addEventListener('drop', this.onCpcsDrop.bind(this));

        this.csvFileField.addEventListener('change', async () => {
            if (this.readyToProcess) {
                await this.submitProcessForm();
            }
        });

        for (let radioInput of this.specOptionRadioInputs) {
            radioInput.addEventListener('change', async () => {
                if (this.readyToProcess) {
                    await this.submitProcessForm();
                }
            });
        }

        this.downloadForm.addEventListener('submit', () => {
            // Let the submit go through, and additionally update status
            this.updateStatus(this.statuses.DOWNLOAD_STARTED);
        });
    }

    get cpcDropZone() {
        return document.getElementById('cpc-drop-zone');
    }
    get dropZonePreview() {
        return document.getElementById('drop-zone-preview');
    }
    get csvFileField() {
        return document.getElementById('id_label_spec_csv');
    }
    get specOptionRadioInputs() {
        return Array.from(
            this.processForm.querySelectorAll(
                'input[name="label_spec_fields"]'));
    }
    get specOptionValue() {
        for (let radioInput of this.specOptionRadioInputs) {
            if (radioInput.checked) {
                return radioInput.value;
            }
        }
        return null;
    }
    get processForm() {
        return document.getElementById('process-form');
    }
    get statusDisplay() {
        return document.getElementById('status_display');
    }
    get statusDetail() {
        return document.getElementById('status_detail');
    }
    get previewTable() {
        return document.getElementById('preview_table');
    }
    get downloadForm() {
        return document.getElementById('download-form');
    }
    get downloadSubmitButton() {
        return this.downloadForm.querySelector('input[type="submit"]');
    }

    get readyToProcess() {
        return this.cpcs.length > 0 && this.csvFileField.files.length > 0;
    }

    setStatusDetailLines(lines) {
        // Clear contents
        this.statusDetail.replaceChildren();

        for (let line of lines) {
            if (this.statusDetail.childNodes.length > 0) {
                this.statusDetail.append(document.createElement('br'));
            }
            this.statusDetail.append(document.createTextNode(line));
        }
    }

    statuses = {
        PROCESSING: 1,
        PROCESS_ERROR: 2,
        READY: 3,
        DOWNLOAD_STARTED: 4,
    }
    updateStatus(newStatus) {
        if (newStatus === this.statuses.PROCESSING) {
            this.downloadSubmitButton.disabled = true;
            this.statusDisplay.textContent = "Processing...";
            this.setStatusDetailLines([]);
            this.previewTable.replaceChildren();
        }
        else if (newStatus === this.statuses.PROCESS_ERROR) {
            this.downloadSubmitButton.disabled = true;
            this.statusDisplay.textContent
                = "Error encountered when processing";
            this.setStatusDetailLines(this.processError.split('\n'));
        }
        else if (newStatus === this.statuses.READY) {
            this.downloadSubmitButton.disabled = false;
            this.statusDisplay.textContent
                = "Processing OK; ready for download";

            let d = this.previewDetails;
            this.setStatusDetailLines([
                `${d.num_files} CPC file(s) processed`,
            ]);

            // Clear contents of preview table
            this.previewTable.replaceChildren();

            // Table header
            let thead = document.createElement('thead');
            this.previewTable.appendChild(thead);
            let headerRow = document.createElement('tr');
            let headers;
            if (this.specOptionValue === 'id_and_notes') {
                headers = [
                    'Old ID', 'Old Notes',
                    'New ID', 'New Notes', 'Applicable Points',
                ];
            }
            else {
                // 'id_only'
                headers = ['Old ID', 'New ID', 'Applicable Points'];
            }
            for (let header of headers) {
                let cell = document.createElement('th');
                cell.textContent = header;
                headerRow.appendChild(cell);
            }
            thead.appendChild(headerRow);

            // Table body
            let tbody = document.createElement('tbody');
            this.previewTable.appendChild(tbody);
            let cellValues;
            for (let specItem of d.label_spec) {
                let row = document.createElement('tr');
                if (this.specOptionValue === 'id_and_notes') {
                    cellValues = [
                        specItem.old_id, specItem.old_notes,
                        specItem.new_id, specItem.new_notes,
                        specItem.point_count,
                    ];
                }
                else {
                    // 'id_only'
                    cellValues = [
                        specItem.old_id,
                        specItem.new_id,
                        specItem.point_count,
                    ];
                }
                for (let cellValue of cellValues) {
                    let cell = document.createElement('td');
                    cell.textContent = cellValue;
                    row.appendChild(cell);
                }
                tbody.appendChild(row);
            }
        }
        else if (newStatus === this.statuses.DOWNLOAD_STARTED) {
            this.downloadSubmitButton.disabled = true;
            // Note that since the download is synchronous, not async, we
            // can't define a callback to run when it finishes.
        }
    }

    async onCpcsDrop(event) {
        // Prevent navigation.
        event.preventDefault();

        this.dropZonePreview.textContent = "";

        let reader = new DataTransferReader(
            {acceptedExtensions: ['cpc'], maxFiles: this.maxCpcFiles}
        );
        this.cpcs = await reader.getFiles(event.dataTransfer.items);

        this.dropZonePreview.textContent =
            `Detected ${this.cpcs.length} .cpc file(s).`;

        if (this.readyToProcess) {
            await this.submitProcessForm();
        }
    }

    async submitProcessForm() {
        this.updateStatus(this.statuses.PROCESSING);

        // To start, get values from the form element.
        let formData = new FormData(this.processForm);

        // Add CPC files and their filepaths.
        //
        // Django doesn't readily support filepaths of file uploads, only
        // filenames. So we'll send the files with placeholder filenames,
        // and use a separate field to define the mapping from placeholders
        // to actual filepaths.
        let cpcFilepaths = {};
        for (let [index, cpc] of this.cpcs.entries()) {
            let placeholderFilename = `${index}.cpc`;
            formData.append('cpc_files', cpc, placeholderFilename);
            cpcFilepaths[placeholderFilename] = cpc.filepath;
        }
        formData.append('cpc_filepaths', JSON.stringify(cpcFilepaths));

        util.fetch(
            this.processForm.action,
            {method: 'POST', body: formData},
            (response) => {

                if (response.error) {
                    this.processError = response.error;
                    this.updateStatus(this.statuses.PROCESS_ERROR);
                    return;
                }

                // Give the session key from the POST response to the
                // download form.
                let sessionDataTimeField = this.downloadForm.querySelector(
                    'input[name="session_data_timestamp"]');
                sessionDataTimeField.value = response.session_data_timestamp;

                this.previewDetails = response.preview_details;
                this.updateStatus(this.statuses.READY);
            }
        );
    }
}


/*
Adapted from:
https://github.com/anatol-grabowski/datatransfer-files-promise
 */
class DataTransferReader {

    constructor({acceptedExtensions = null, maxFiles = null} = {}) {
        this.acceptedExtensions = acceptedExtensions;
        this.maxFiles = maxFiles;
        this.totalFilesRead = 0;
        this.warnedAboutFileCount = false;
    }

    isFileAccepted(file) {
        if (!this.acceptedExtensions) {
            // All extensions are accepted.
            return true;
        }
        let extension = file.name.split('.').pop().toLowerCase();
        return this.acceptedExtensions.includes(extension);
    }

    incrementFilesReadCount() {
        if (this.warnedAboutFileCount) {
            // If the user decides to keep going, we don't want to repeatedly
            // warn on <threshold> files, <threshold+1> files, etc.
            return;
        }

        this.totalFilesRead++;
        if (this.totalFilesRead > this.maxFiles) {
            let keepGoing = window.confirm(`You've dragged in a lot of files (over ${this.maxFiles}, including non-cpc). Is this what you wanted to do? Select OK to keep scanning, or select Cancel to abort.`);
            this.warnedAboutFileCount = true;

            if (!keepGoing) {
                // We just let this error cancel the rest of the drop
                // handler and propagate to the JS console.
                throw new Error("Aborted after high file count check.");
            }
        }
    }

    readFile(entry, path = '') {
        return new Promise((resolve, reject) => {
            entry.file(file => {
                // Save full path
                file.filepath = path + file.name;
                resolve(file);
            }, (err) => {
                // Don't really know when this happens yet.
                window.alert(`Error while setting up File: ${err}`);
                reject(err);
            })
        })
    }

    dirReadEntries(dirReader, path) {
        return new Promise((resolve, reject) => {
            dirReader.readEntries(async entries => {
                let files = [];
                for (let entry of entries) {
                    const itemFiles = await this.getFilesFromEntry(entry, path);
                    files = files.concat(itemFiles);
                }
                resolve(files);
            }, (err) => {
                // Don't really know when this happens yet.
                window.alert(`Error while reading directory: ${err}`);
                reject(err);
            })
        })
    }

    async readDir(entry, path) {
        const dirReader = entry.createReader();
        const newPath = path + entry.name + '/';
        let files = [];
        let newFiles;

        // Each readEntries call only returns up to 100 entries in a
        // directory (at least in Chrome). Must call readEntries repeatedly
        // until it returns an empty array.
        do {
            newFiles = await this.dirReadEntries(dirReader, newPath);
            files = files.concat(newFiles);
        } while (newFiles.length > 0);

        return files;
    }

    async getFilesFromEntry(entry, path = '') {
        if (entry.isFile) {
            const file = await this.readFile(entry, path);
            this.incrementFilesReadCount();
            if (this.isFileAccepted(file)) {
                return [file];
            }
            else {
                return [];
            }
        }
        if (entry.isDirectory) {
            const files = await this.readDir(entry, path);
            return files;
        }
        // throw new Error('Entry not isFile and not isDirectory - unable to get files')
    }

    async getFiles(dataTransferItems) {
        let files = [];
        let entries = [];

        // Pull out all entries before reading them
        for (let i = 0, ii = dataTransferItems.length; i < ii; i++) {
            entries.push(dataTransferItems[i].webkitGetAsEntry());
        }

        // Recursively read through all entries
        for (let entry of entries) {
            if (!entry) {
                // Perhaps something other than a file/folder was dropped
                continue;
            }
            const newFiles = await this.getFilesFromEntry(entry);
            files = files.concat(newFiles);

            if (files.length > this.maxFiles) {
                let message = `Exceeded .cpc file limit of ${this.maxFiles}.`;
                window.alert(message);
                // We just let this error cancel the rest of the drop
                // handler and propagate to the JS console.
                throw new Error(message);
            }
        }

        return files;
    }
}
