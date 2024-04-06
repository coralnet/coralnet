const { test } = QUnit;

import Poller from '/static/js/Poller.js';
import { useFixture } from '/static/js/test-utils.js';


QUnit.module("Main", (hooks) => {
    hooks.beforeEach(async() => {
        useFixture('main');
    });

    test("finish on first poll", async function(assert) {
        let poller = new Poller(
            async() => {
                return 1.0;
            },
            10,
        );
        poller.startPolling();
        let finishMessage = await poller.finishPromise;

        assert.equal(finishMessage, "Success", "Polling should finish");
        assert.deepEqual(
            poller.previousPolls,
            [[10, 0.0]],
            "Polling should have gone as expected");
    });

    test("steady progress across multiple polls", async function(assert) {
        let progress = 0.0;
        let poller = new Poller(
            async() => {
                progress += 0.25;
                return progress;
            },
            10,
        );
        poller.startPolling();
        let finishMessage = await poller.finishPromise;

        assert.equal(finishMessage, "Success", "Polling should finish");
        assert.deepEqual(
            poller.previousPolls,
            [[10, 0.0], [10, 0.25], [10, 0.5], [10, 0.75]],
            "Polling should have gone as expected");
    });

    test("backoff due to pause in progress", async function(assert) {
        let progressArray = [0.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.7, 0.9, 1.0];
        let progressIndex = 0;
        let poller = new Poller(
            async() => {
                progressIndex++;
                return progressArray[progressIndex];
            },
            10,
        );
        poller.startPolling();
        let finishMessage = await poller.finishPromise;

        assert.equal(finishMessage, "Success", "Polling should finish");
        assert.deepEqual(
            poller.previousPolls,
            [
                [10, 0.0], [10, 0.5], [10, 0.5],
                // Backoff
                [20, 0.5], [40, 0.5], [80, 0.5],
                // Still longer intervals as progress continues
                [80, 0.7], [80, 0.9],
            ],
            "Polling should have gone as expected");
    });

    test("backoff due to slow progress", async function(assert) {
        let progressArray = [0.0, 0.1, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0];
        let progressIndex = 0;
        let poller = new Poller(
            async() => {
                progressIndex++;
                return progressArray[progressIndex];
            },
            10,
            {backoffProgress: 0.33},
        );
        poller.startPolling();
        let finishMessage = await poller.finishPromise;

        assert.equal(finishMessage, "Success", "Polling should finish");
        assert.deepEqual(
            poller.previousPolls,
            [
                [10, 0.0], [10, 0.1],
                // Backoff
                [20, 0.2], [40, 0.4],
                // Reached the non-backoff threshold
                [40, 0.6], [40, 0.8],
                // More backoff
                [80, 0.9],
            ],
            "Polling should have gone as expected");
    });

    test("reaching max interval", async function(assert) {
        let progressArray = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 1.0];
        let progressIndex = 0;
        let poller = new Poller(
            async() => {
                progressIndex++;
                return progressArray[progressIndex];
            },
            10,
            {backoffProgress: 0.33, maxInterval: 50},
        );
        poller.startPolling();
        let finishMessage = await poller.finishPromise;

        assert.equal(finishMessage, "Success", "Polling should finish");
        assert.deepEqual(
            poller.previousPolls,
            [
                [10, 0.0], [10, 0.1],
                // Backoff
                [20, 0.2], [40, 0.3],
                // Reached the max interval
                [50, 0.4], [50, 0.5], [50, 0.6], [50, 0.7],
            ],
            "Polling should have gone as expected");
    });

    test("giving up", async function(assert) {
        let progressArray = [
            0.0, 0.4, 0.8, 0.8, 0.8, 0.8,
            0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 1.0];
        let progressIndex = 0;
        let poller = new Poller(
            async() => {
                progressIndex++;
                return progressArray[progressIndex];
            },
            10,
            {backoffProgress: 0.2, maxInterval: 20, giveUpInterval: 100},
        );
        poller.startPolling();
        let finishMessage = await poller.finishPromise
            .catch((message) => {
                return message;
            });

        assert.equal(
            finishMessage, "Gave up due to lack of progress",
            "Polling should give up");
        assert.deepEqual(
            poller.previousPolls,
            [
                [10, 0.0], [10, 0.4], [10, 0.8], [10, 0.8],
                // Backoff
                [20, 0.8], [20, 0.8],
                // Sufficiently long period of no progress
                [20, 0.9], [20, 0.9], [20, 0.9], [20, 0.9], [20, 0.9],
            ],
            "Polling should have gone as expected");
    });

    test("error in poll func", async function(assert) {
        let iteration = 0;
        let poller = new Poller(
            async() => {
                iteration++;
                switch(iteration) {
                    case 1:
                        return 0.1;
                    case 2:
                        return 0.2;
                    default:
                        throw new Error("Poll error");
                }
            },
            10,
        );
        poller.startPolling();
        let finishMessage = await poller.finishPromise
            .catch((message) => {
                return message;
            });

        assert.equal(
            finishMessage, "Poll error",
            "Polling should stop with the expected error");
        assert.deepEqual(
            poller.previousPolls,
            [
                [10, 0.0], [10, 0.1], [10, 0.2],
            ],
            "Polling should have gone as expected");
    });
});
