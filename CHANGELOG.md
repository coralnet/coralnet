# Changelog


For general instructions on how to update a development environment of CoralNet, see "Updating to the latest repository code" in `docs/server_operation.rst`. This changelog has specific instructions/notes for each CoralNet version.

For info about the semantic versioning used here, see `docs/versions.rst`.


## 1.8 (WIP)

- New migration to run for `jobs`. If `api_core` 0004 runs into issues, try running the new `jobs` 0011 migration first.
- New package to install: diskcache 5.6.3
- Clear the current contents of the Django cache folder (`<SITE_DIR>/tmp/django_cache` by default). The format of cache files saved to this directory will be different from before.
- The `update_label_details` periodic-job should be run at least once to compute labels' annotation counts and popularities.

## [1.7](https://github.com/coralnet/coralnet/tree/1.7)

- The new `EXTRACTORS_BUCKET` setting is now required when using a non-dummy feature extractor.
- The `MIN_NBR_ANNOTATED_IMAGES` setting has been renamed to `TRAINING_MIN_IMAGES`. Also, it's now tied to the corresponding pyspacer setting, which means that lowering this number will speed up unit tests.
- The `GOOGLE_MAPS_API_KEY` setting is no longer used.
- Updates to required packages:
  - pyspacer 0.4.1 -> 0.6.1
  - Pillow 9.4.0 -> 10.1.0
- New migrations to run for `annotations`, `events`, and `vision_backend`. annotations 0023 could possibly take hours per million images.

## [1.6](https://github.com/coralnet/coralnet/tree/1.6)

- Updates to required packages:
  - pyspacer 0.4.0 -> 0.4.1
  - numpy is now pinned to match pyspacer's requirements.txt
- New migrations to run for `jobs` and `vision_backend`.

## [1.5](https://github.com/coralnet/coralnet/tree/1.5)

- Python version has been updated from 3.6 to 3.10. See Server Operation > Upgrading Python in the CoralNet docs.
- Settings scheme has been changed. The old scheme used a developer-specific `.py` file AND a `secrets.json` file. The new scheme uses a `.env` file OR environment variables. Check the updated installation docs for details.
- Updates to required packages. Check requirements files for all the changes, but most notably:
  - Django 2.2.x -> 4.1.x
  - easy-thumbnails 2.6.0 -> our own fork
  - pyspacer 0.3.1 -> 0.4.0
- PostgreSQL version has been updated from 10 to 14. See Server Operation > Upgrading PostgreSQL in the CoralNet docs. CoralNet doesn't have any PostgreSQL-version-specific steps for this upgrade.
- New migrations to run for `api_core`, `calcification`, `labels`, `vision_backend`, Django's `auth`, and django-reversion's `reversion`.

### Notes

- A regression: unit tests now have 'noisy' log messages again, because the use of assertLogs() (replacing patch_logger() which was removed in Django 3.0) requires logging to be enabled. Ideally this regression would be fixed by reconfiguring (instead of disabling) the logging during tests, but that's something to figure out for a later release.
- Page header and footer nav-button styling has been cleaned up, so hopefully the shadowing makes a bit more sense now.

## [1.4](https://github.com/coralnet/coralnet/tree/1.4)

- Updates to required packages:
  - Removed `celery`.
  - Removed celery dependencies `amqp`, `anyjson`, `billiard`, and `kombu`.
  - Added `huey>=2.4.4,<2.5`.
  - Updated `redis==2.10.5` to `redis>=4.3.5,<4.4`.
- ``CELERY_ALWAYS_EAGER`` setting has been replaced with ``HUEY['immediate']``.
- Feel free to clean up any celery-generated files, such as the logs and schedule.

## [1.3](https://github.com/coralnet/coralnet/tree/1.3)

- Updates to required packages:
  - Removed `boto`.
  - Added `boto3==1.23.10`.

## [1.2](https://github.com/coralnet/coralnet/tree/1.2)

**Before updating from 1.1 to 1.2,** ensure that all spacer jobs and BatchJobs have finished first, because 1) spacer job token formats have changed for train and deploy, and 2) the migrations will be abandoning all existing BatchJobs. To do this:
  - Stop the web server and celery processes.
  - If using BatchQueue, check the AWS Batch console to ensure all your BatchJobs have finished. If using LocalQueue, then no waiting is needed here.
  - Manually run `collect_all_jobs()` in the shell to collect those jobs.

Once that's done, update to 1.2, then:

- Run migrations for ``api_core``, ``jobs`` (new app), and ``vision_backend``. Expect moderate runtime to process existing BatchJobs.

- Do an announcement after updating production. The new job-monitoring page for sources will hopefully answer many questions of the form "what's happening with the classifiers in my source?".

## [1.1](https://github.com/coralnet/coralnet/tree/1.1)

Update instructions have not been well tracked up to this point. If the migrations give you trouble, consider starting your environment fresh from 1.2 or later.

## [1.0](https://github.com/coralnet/coralnet/tree/1.0)

See [blog post](https://coralnet.ucsd.edu/blog/coralnet-is-officially-out-of-beta/) for major changes associated with this release.