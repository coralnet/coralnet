/* Dependencies: util */

class AsyncMedia {

    INITIAL_POLL_INTERVAL = 2*1000;

    /* Generate any page media that weren't available before the page was
       requested. */
    startGeneratingAsyncMedia() {
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
        let numGenerationRequests = 0;
        this.poller = new Poller(
            this.pollForMedia.bind(this), this.INITIAL_POLL_INTERVAL);

        for (let mediaBatchKey of mediaBatchKeys) {
            let formData = new FormData();
            formData.append('media_batch_key', mediaBatchKey);

            util.fetch(
                window.startMediaGenerationURL,
                {
                    method: 'POST',
                    body: formData,
                    headers: {'X-CSRFToken': csrfToken},
                    // Do not send CSRF token to another domain.
                    mode: 'same-origin',
                },
                (response) => {
                    if (response.hasOwnProperty('error')) {
                        console.log(
                            `Problem generating images: ${response['error']}`);
                        return;
                    }

                    numGenerationRequests++;

                    if (numGenerationRequests === mediaBatchKeys.length) {
                        // Start periodically polling the server for generated
                        // media.
                        this.poller.startPolling();
                    }
                }
            );
        }
    }

    pollForMedia() {
        // Focus on only one media batch at a time, if there are multiple.
        let mediaBatchKey = Object.keys(this.mediaBatches)[0];
        let searchParams = new URLSearchParams({
            'media_batch_key': mediaBatchKey,
        });

        return util.fetch(
            window.pollForMediaURL + '?' + searchParams.toString(),
            {method: 'GET'},
            (response) => {
                if (response.hasOwnProperty('error')) {
                    console.log(
                        `Problem loading images: ${response['error']}`);
                    return null;
                }

                this.handleMediaResults(
                    mediaBatchKey, response['mediaResults']);

                // Return progress out of 1.0.
                return this.loadedMedia / this.mediaCount;
            }
        );
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

let asyncMedia = new AsyncMedia();
window.addEventListener(
    'load', asyncMedia.startGeneratingAsyncMedia.bind(asyncMedia));

// TODO: Relevant JS tests would include:
// - All/some/none async media already generated
// - Single poll gets all URLs
// - Multiple polls required to get all URLs
// - Multiple batches of async media
// - Problem generating images
// - Problem loading images
