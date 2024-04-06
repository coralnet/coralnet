import Poller from '/static/js/Poller.js';
/* Non-imported dependencies: util */


class AsyncMedia {

    INITIAL_POLL_INTERVAL = 2*1000;

    /* Generate any page media that weren't available before the page was
       requested. */
    async startGeneratingAsyncMedia() {
        this.mediaBatches = {};
        this.mediaCount = 0;
        this.loadedMedia = 0;

        // The media-async class denotes that an img is eligible for
        // async generation.
        document.querySelectorAll('img.media-async').forEach((img) => {
            let mediaBatchKey = img.dataset.mediaBatchKey;
            let mediaKey = img.dataset.mediaKey;
            if (mediaKey !== '') {
                // Non-empty mediaKey denotes that an img needs generation.
                if (!this.mediaBatches.hasOwnProperty(mediaBatchKey)) {
                    this.mediaBatches[mediaBatchKey] = {};
                }
                this.mediaBatches[mediaBatchKey][mediaKey] = img;
                this.mediaCount++;
            }
        });

        // Stop if there are no such img elements.
        let mediaBatchKeys = Object.keys(this.mediaBatches);
        if (mediaBatchKeys.length === 0) {
            return;
        }

        let csrfToken =
            document.querySelector('[name=csrfmiddlewaretoken]').value;
        let startGenerationPromises = [];
        this.poller = new Poller(
            this.pollForMedia.bind(this), this.INITIAL_POLL_INTERVAL);

        for (let mediaBatchKey of mediaBatchKeys) {
            let formData = new FormData();
            formData.append('media_batch_key', mediaBatchKey);

            let promise = util.fetch(
                globalThis.startMediaGenerationURL,
                {
                    method: 'POST',
                    body: formData,
                    headers: {'X-CSRFToken': csrfToken},
                    // Do not send CSRF token to another domain.
                    mode: 'same-origin',
                }
            )
                .then((response) => {
                    if (response.hasOwnProperty('error')) {
                        throw new Error(
                            `Problem generating images: ${response['error']}`);
                    }
                    return response;
                });
            startGenerationPromises.push(promise);
        }

        return Promise.all(startGenerationPromises)
            .then(() => {
                // Requested generation for each batch.
                // Start periodically polling the server for generated
                // media.
                this.poller.startPolling();
            });
    }

    pollForMedia() {
        // Focus on only one media batch at a time, if there are multiple.
        let mediaBatchKey = Object.keys(this.mediaBatches)[0];
        let searchParams = new URLSearchParams({
            'media_batch_key': mediaBatchKey,
        });

        return util.fetch(
            globalThis.pollForMediaURL + '?' + searchParams.toString(),
            {method: 'GET'},
        )
            .then((response) => {
                if (response.hasOwnProperty('error')) {
                    throw new Error(
                        `Problem loading images: ${response['error']}`);
                }

                this.handleMediaResults(
                    mediaBatchKey, response['mediaResults']);

                // Return progress out of 1.0.
                return this.loadedMedia / this.mediaCount;
            });
    }

    handleMediaResults(mediaBatchKey, mediaResults) {
        let mediaBatch = this.mediaBatches[mediaBatchKey];

        for (
            let [mediaKey, url]
            of Object.entries(mediaResults)
        ) {
            // A media file's URL.
            // Load it into the img element.
            let imgElement = mediaBatch[mediaKey];
            imgElement.src = url;
            this.loadedMedia++;

            // Remove from our bookkeeping hash.
            delete mediaBatch[mediaKey];

            // And remove the batch from bookkeeping if it's done.
            if (Object.keys(mediaBatch).length === 0) {
                delete this.mediaBatches[mediaBatchKey];
            }
        }
    }
}

export default AsyncMedia;
