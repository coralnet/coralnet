Tips for CoralNet developers
============================


Migration unit tests
--------------------

We test migrations by inheriting the class ``MigrationTest`` from the ``django-migration-testcase`` package. This is a useful and fairly small-scoped package, but it's no longer maintained and does have things to watch out for.

Note that as part of their operation, MigrationTests run all migrations backwards and all migrations forwards, regardless of the scope of the ``before`` and ``after`` migrations defined in the class. So if you see your MigrationTest fail with messages that seem to have nothing to do with the test, that may be why. It probably still indicates an actual bug, but whether it's worth fixing is up to discretion, particularly if the migrations are planned to be squashed soon.

Also note that MigrationTests might not clean up after themselves after they fail, which may lead to strange failures in subsequently-running tests. So, focus on fixing the first test that failed.