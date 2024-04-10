function useFixture(fixtureName) {
    // This assumes the #qunit-fixture element currently contains all the
    // fixtures we've defined. We'll remove all except the desired fixture.
    document.querySelectorAll('.fixture-option').forEach((fixtureElement) => {
        if (fixtureElement.dataset.fixtureName !== fixtureName) {
            fixtureElement.remove();
        }
    });
}

export { useFixture };
