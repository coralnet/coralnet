const { test } = QUnit;
import fetchMock from '/static/js/fetch-mock.js';

import AnnotationToolImageHelper from '/static/js/AnnotationToolImageHelper.js';
import { useFixture } from '/static/js/test-utils.js';

let imageHelper;
let SCALED_WIDTH = 800;
let SCALED_HEIGHT = 600;
let FULL_WIDTH = 3200;
let FULL_HEIGHT = 2400;


function instantiate() {
    imageHelper = new AnnotationToolImageHelper(
        {
            'scaled': {
                'url': 'scaled.jpg',
                'width': SCALED_WIDTH,
                'height': SCALED_HEIGHT,
            },
            'full': {
                'url': 'full.jpg',
                'width': FULL_WIDTH,
                'height': FULL_HEIGHT,
            },
        },
        null,
        {},
    );
}


function instantiateFullOnly() {
    imageHelper = new AnnotationToolImageHelper(
        {
            'full': {
                'url': 'full.jpg',
                'width': FULL_WIDTH,
                'height': FULL_HEIGHT,
            },
        },
        null,
        {},
    );
}


async function setImage(
    filename, width, height, color, toAwaitBeforeLoad=null)
{
    let canvas = document.createElement('canvas');
    canvas.width = width;
    canvas.height = height;
    let context = canvas.getContext('2d');
    context.fillStyle = color;
    context.fillRect(0, 0, canvas.width, canvas.height);

    let imageContentType = 'image/jpeg';
    let blob = await new Promise(
        resolve => canvas.toBlob(resolve, imageContentType));
    let imageAsBinaryString =
        await AnnotationToolImageHelper.readBlob(blob);

    let uint8Array = Uint8Array.from(
        imageAsBinaryString, c => c.charCodeAt(0));
    blob = new Blob([uint8Array], {type: imageContentType});

    if (toAwaitBeforeLoad) {
        // A Promise has been given which allows the fetch-caller and
        // the fetch-callback to wait for each other.
        // 1. Caller waits for the callback's about-to-load resolution. Then
        //    the caller can run some code, such as asserting expected state
        //    at this point.
        // 2. Callback waits for the caller's to-await-before-load resolution.
        //    Then the callback here can proceed with loading the image.
        let {promise: aboutToLoadPromise, resolve: atlResolve, reject}
            = Promise.withResolvers();
        let fetchCallback = async (url, options, request) => {
            atlResolve();
            await toAwaitBeforeLoad;
            return new Response(blob);
        };
        fetchMock.get(filename, fetchCallback);
        // We want to return the aboutToLoadPromise to the caller. To do so,
        // we wrap the aboutToLoadPromise in a hash; because if we didn't
        // wrap this Promise in anything, this Promise would become the
        // Promise that's 'used up' by the `await setImage(...)` call.
        return {'promise': aboutToLoadPromise};
    }
    else {
        fetchMock.get(filename, new Response(blob));
    }
}


QUnit.module("Load basic images", (hooks) => {
    hooks.beforeEach(async () => {
        useFixture('main');
    });
    hooks.afterEach(() => {
        fetchMock.reset();
    });

    test("full image only", async function(assert) {
        await setImage('full.jpg', FULL_WIDTH, FULL_HEIGHT, 'red');
        instantiateFullOnly();
        await imageHelper.loadSourceImages();

        // Get any pixel (the first pixel, here).
        let pixelData = imageHelper.imageCanvas
            .getContext('2d').getImageData(0, 0, 1, 1).data;
        let [red, green, blue, _alpha] = pixelData;

        // This is jpg, so we don't expect a perfectly faithful
        // (255,0,0) red.
        // Instead just ensure this pixel is 'red enough'.
        assert.true(
            red - green - blue > 200,
            "Should have loaded the image, so an arbitrary pixel should be" +
            " close to red");
    });

    test("scaled image then full image", async function(assert) {
        let {promise: checkedScaledImagePromise, resolve: csipResolve, reject}
            = Promise.withResolvers();

        await setImage('scaled.jpg', SCALED_WIDTH, SCALED_HEIGHT, 'blue');
        let {promise: fullImageAboutToLoadPromise} = await setImage(
            'full.jpg', FULL_WIDTH, FULL_HEIGHT, 'red',
            checkedScaledImagePromise,
        );
        instantiate();
        let fullImageLoadedPromise = imageHelper.loadSourceImages();

        // Wait for loading to proceed far enough so that the scaled image
        // is loaded, but the full image isn't yet.
        await fullImageAboutToLoadPromise;
        let pixelData = imageHelper.imageCanvas
            .getContext('2d').getImageData(0, 0, 1, 1).data;
        let [red, green, blue, _alpha] = pixelData;
        assert.true(
            blue - red - green > 200,
            "Should have loaded the scaled image, so an arbitrary pixel" +
            " should be close to blue");

        // Allow loading of the full image to proceed.
        csipResolve();
        await fullImageLoadedPromise;
        pixelData = imageHelper.imageCanvas
            .getContext('2d').getImageData(0, 0, 1, 1).data;
        [red, green, blue, _alpha] = pixelData;
        assert.true(
            red - green - blue > 200,
            "Should have loaded the full image, so an arbitrary pixel" +
            " should be close to red");
    });
});
