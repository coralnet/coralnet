const { test } = QUnit;
import fetchMock from '/static/js/fetch-mock.js';

import AsyncMedia from '/static/js/AsyncMedia.js';
import { useFixture } from '/static/js/test-utils.js';


QUnit.module("Main", (hooks) => {
    hooks.beforeEach(async() => {
        useFixture('main');
    });
    hooks.afterEach(() => {
        // Restore fetch() to its native implementation
        fetchMock.reset();
    });

    test("finish on first poll", async function(assert) {

        // Mock the start-generation request so we don't actually hit the
        // Django server.
        fetchMock.post(
            globalThis.startMediaGenerationURL,
            // Response config as JSON
            // https://github.com/wheresrhys/fetch-mock/blob/main/docs/cheatsheet.md#response-configuration
            {success: true},
        );
        // Mock the poll request to avoid hitting the Django server and
        // guarantee a particular response.
        fetchMock.get(
            {
                url: globalThis.pollForMediaURL,
                // If query args are present in the fetch call, they must be
                // specified here for the fetch call to be captured.
                query: {media_batch_key: 'batch1'},
            },
            // Response config as JSON
            {mediaResults: {
                'media1': '/media/images/media1.png',
                'media2': '/media/images/media2.png',
            }},
        );

        let asyncMedia = new AsyncMedia();
        await asyncMedia.startGeneratingAsyncMedia();
        let finishMessage = await asyncMedia.poller.finishPromise;

        assert.equal(
            asyncMedia.mediaCount, 2,
            "Should have detected 2 media to generate");
        assert.equal(finishMessage, "Success", "Polling should finish");
        assert.true(
            document.querySelector('img[data-media-key="media1"]').src
            .endsWith('/media/images/media1.png'),
            "media1 src should be filled in");
        assert.true(
            document.querySelector('img[data-media-key="media2"]').src
            .endsWith('/media/images/media2.png'),
            "media2 src should be filled in");

        assert.deepEqual(
            asyncMedia.poller.previousPolls,
            [[2000, 0.0]],
            "Polling should have gone as expected");
    });

    test("finish with 2 polls", async function(assert) {

        fetchMock.post(
            globalThis.startMediaGenerationURL,
            {success: true},
        );

        fetchMock.get(
            {
                url: globalThis.pollForMediaURL,
                query: {'media_batch_key': 'batch1'},
            },
            // Response config as a function returning JSON
            // https://github.com/wheresrhys/fetch-mock/blob/main/docs/cheatsheet.md#response-configuration
            (url, options, request) => {
                if (asyncMedia.loadedMedia === 1) {
                    return {'mediaResults': {
                        'media1': '/media/images/media1.png',
                    }};
                }
                return {'mediaResults': {
                    'media2': '/media/images/media2.png',
                }};
            },
        );

        let asyncMedia = new AsyncMedia();
        await asyncMedia.startGeneratingAsyncMedia();
        let finishMessage = await asyncMedia.poller.finishPromise;

        assert.equal(
            asyncMedia.mediaCount, 2,
            "Should have detected 2 media to generate");
        assert.equal(finishMessage, "Success", "Polling should finish");
        assert.true(
            document.querySelector('img[data-media-key="media1"]').src
            .endsWith('/media/images/media1.png'),
            "media1 src should be filled in");
        assert.true(
            document.querySelector('img[data-media-key="media2"]').src
            .endsWith('/media/images/media2.png'),
            "media2 src should be filled in");

        assert.deepEqual(
            asyncMedia.poller.previousPolls,
            [[2000, 0.0], [2000, 0.5]],
            "Polling should have gone as expected");
    });

    test("1 already generated", async function(assert) {

        // Change one DOM img element to have an empty media key;
        // this denotes that the media is already generated
        document.querySelector('img[data-media-key="media1"]')
            .dataset.mediaKey = '';

        fetchMock.post(
            globalThis.startMediaGenerationURL,
            {success: true},
        );
        fetchMock.get(
            {
                url: globalThis.pollForMediaURL,
                query: {media_batch_key: 'batch1'},
            },
            {mediaResults: {
                'media2': '/media/images/media2.png',
            }},
        );

        let asyncMedia = new AsyncMedia();
        await asyncMedia.startGeneratingAsyncMedia();
        let finishMessage = await asyncMedia.poller.finishPromise;

        assert.equal(
            asyncMedia.mediaCount, 1,
            "Should have detected 1 media to generate");
        assert.equal(finishMessage, "Success", "Polling should finish");
        assert.true(
            document.querySelector('img[data-media-key="media2"]').src
            .endsWith('/media/images/media2.png'),
            "media2 src should be filled in");

        assert.deepEqual(
            asyncMedia.poller.previousPolls,
            [[2000, 0.0]],
            "Polling should have gone as expected");
    });

    test("both already generated", async function(assert) {

        document.querySelector('img[data-media-key="media1"]')
            .dataset.mediaKey = '';
        document.querySelector('img[data-media-key="media2"]')
            .dataset.mediaKey = '';

        let asyncMedia = new AsyncMedia();
        await asyncMedia.startGeneratingAsyncMedia();

        assert.equal(
            asyncMedia.mediaCount, 0,
            "Should have detected 0 media to generate");
    });

    test("problem generating", async function(assert) {

        fetchMock.post(
            globalThis.startMediaGenerationURL,
            {error: "Problem detail goes here"},
        );

        let asyncMedia = new AsyncMedia();
        let errorMessage;
        await asyncMedia.startGeneratingAsyncMedia()
            .catch((error) => {
                errorMessage = error.message;
            });
        assert.equal(
            errorMessage,
            "Problem generating images: Problem detail goes here",
            "Should have thrown the expected error");
    });

    test("problem loading", async function(assert) {

        fetchMock.post(
            globalThis.startMediaGenerationURL,
            {success: true},
        );
        fetchMock.get(
            {
                url: globalThis.pollForMediaURL,
                query: {media_batch_key: 'batch1'},
            },
            {error: "Problem detail goes here"},
        );

        let asyncMedia = new AsyncMedia();
        let errorMessage;
        await asyncMedia.startGeneratingAsyncMedia();
        await asyncMedia.poller.finishPromise
            .then(
                // Resolve function
                () => {},
                // Reject function
                (message) => {
                    errorMessage = message;
                },
            )

        assert.equal(
            errorMessage,
            "Problem loading images: Problem detail goes here",
            "Promise should produce the expected error");
    });
});
