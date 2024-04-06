class Poller {

    constructor(
        // Function to call on each poll; should return a Promise which
        // resolves to a progress number between 0.0 (none) and 1.0 (complete).
        func,
        // Initial interval to wait between polls.
        initialInterval,
        // If after this many polls, the progress ratio has advanced less than
        // this much, back off by increasing the interval by this factor.
        backoffPolls = 2,
        backoffProgress = 0.01,
        backoffIntervalFactor = 2.0,
        // Max polling interval.
        maxInterval = 60*1000,
        // After polling for this long with 0 progress, give up completely.
        giveUpInterval = 5*60*1000,
    ) {
        this.func = func;
        this.initialInterval = initialInterval;
        this.backoffPolls = backoffPolls;
        this.backoffProgress = backoffProgress;
        this.backoffIntervalFactor = backoffIntervalFactor;
        this.maxInterval = maxInterval;
        this.giveUpInterval = giveUpInterval;

        this.previousPolls = [];

        // withResolvers was introduced in most browsers around March 2024.
        // We use it to help with certain QUnit tests.
        // If it's not detected in the browser, we make sure the non-test
        // functionality still works.
        if (Promise.withResolvers) {
            let {promise, resolve, reject} = Promise.withResolvers();
            // This promise can be awaited to indicate when the polling is
            // finished.
            this.finishPromise = promise;
            this.resolveFinishPromise = resolve;
            this.rejectFinishPromise = reject;
        }
        else {
            // Here we do the bare minimum to not affect non-test
            // functionality. The QUnit tests will break.
            this.finishPromise = null;
            this.resolveFinishPromise = () => {};
            this.rejectFinishPromise = () => {};
        }
    }

    getNextInterval(progress) {
        let numPolls = this.previousPolls.length;
        let [mostRecentInterval, _mostRecentProgress] =
            this.previousPolls[numPolls - 1];

        if (numPolls < this.backoffPolls) {
            // Not enough polls to check for the backoff criteria yet.
            return mostRecentInterval;
        }

        let [_comparisonInterval, comparisonProgress] =
            this.previousPolls[numPolls - this.backoffPolls];
        if (progress - comparisonProgress >= this.backoffProgress) {
            // Enough recent progress has been made to not back off yet.
            return mostRecentInterval;
        }

        let sumOfRecentIntervals = 0;
        for (let index = numPolls - 1; index >= 0; index--) {
            let [pollInterval, pollProgress] = this.previousPolls[index];

            if (pollProgress < progress) {
                // There's been progress within the giveUpInterval; don't
                // give up yet.
                break;
            }

            sumOfRecentIntervals += pollInterval;
            if (sumOfRecentIntervals >= this.giveUpInterval) {
                // No progress made within the giveUpInterval; give up.
                return null;
            }
        }

        // Backing off, but not giving up yet.
        return Math.min(
            mostRecentInterval * this.backoffIntervalFactor,
            this.maxInterval,
        );
    }

    async poll() {
        this.func()
            .then((progress) => {
                if (progress >= 1.0) {
                    this.resolveFinishPromise("Success");
                    return;
                }

                let nextInterval = this.getNextInterval(progress);
                if (nextInterval === null) {
                    this.rejectFinishPromise("Gave up due to lack of progress");
                    return;
                }

                this.previousPolls.push([nextInterval, progress]);
                globalThis.setTimeout(this.poll.bind(this), nextInterval);
            })
            .catch((error) => {
                this.rejectFinishPromise(error.message);
            });
    }

    startPolling() {
        let interval = this.initialInterval;
        this.previousPolls.push([interval, 0.0]);
        globalThis.setTimeout(this.poll.bind(this), interval);
    }
}

export default Poller;

// TODO: Relevant JS tests would include:
// - Backoff
// - Max interval not exceeded
// - Giving up
