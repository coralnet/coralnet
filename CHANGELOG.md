# Changelog


For general instructions on how to update a development environment of CoralNet, see "Updating to the latest repository code" in `docs/server_operation.rst`. This changelog has specific instructions/notes for each CoralNet version.

For info about the semantic versioning used here, see `docs/versions.rst`.

"Production:" dates under each version indicate when the production server was updated to that version.


## [1.21](https://github.com/coralnet/coralnet/tree/1.21)

Production: 2025-07-06

- New migrations to run for `images`. The longest ones are migration 0042 (about 8 minutes per million images) and 0047 (about 40 seconds per million images).

## [1.20](https://github.com/coralnet/coralnet/tree/1.20)

Production: 2025-06-22

- Updates to required packages:
  - pyspacer 0.11.0 -> 0.12.0
  - selenium 3.141.0 -> 4.33.0
- New migrations to run for `annotations`, involving creation of potentially large indexes. Took 30 minutes to run in production.

## [1.19.5](https://github.com/coralnet/coralnet/tree/1.19.5)

Production: 2025-03-01

## [1.19.4](https://github.com/coralnet/coralnet/tree/1.19.4)

Production: 2025-03-01

## [1.19.3](https://github.com/coralnet/coralnet/tree/1.19.3)

Production: 2025-02-27

## [1.19.2](https://github.com/coralnet/coralnet/tree/1.19.2)

Production: 2025-02-21

- Fixed setting of finish dates for new API jobs. To update from 1.19.1, unapply and then reapply migration 0013 yet again.

## [1.19.1](https://github.com/coralnet/coralnet/tree/1.19.1)

Production: 2025-02-21

- Migration 0013 for `api_core` has been fixed, so that finished API jobs with one or more failed units still get finish dates like they're supposed to. To update from 1.19, unapply and then reapply migration 0013.

## [1.19](https://github.com/coralnet/coralnet/tree/1.19)

Production: 2025-02-20

- New package to install: matplotlib==3.10.0
- New migrations to run for `api_core`. Runtime was 5 minutes in production (with about 9000 ApiJobs of 100 units each).

## [1.18.1](https://github.com/coralnet/coralnet/tree/1.18.1)

Production: 2025-01-12

## [1.18](https://github.com/coralnet/coralnet/tree/1.18)

Production: 2024-12-22

- New migrations to run for `annotations`.

## [1.17.1](https://github.com/coralnet/coralnet/tree/1.17.1)

Production: 2024-12-19

## [1.17](https://github.com/coralnet/coralnet/tree/1.17)

Production: 2024-12-17

- New migrations to run for `labels`.

## [1.16](https://github.com/coralnet/coralnet/tree/1.16)

Production: 2024-12-08

- Updates to required packages:
  - boto3 >=1.26.122,<1.27 -> >=1.34.162,<1.35
  - numpy 1.24.1 -> 2.1.3
  - Pillow 10.3.0 -> 11.0.0
  - pyspacer 0.9.0 -> 0.11.0

## [1.15.1](https://github.com/coralnet/coralnet/tree/1.15.1)

Production: 2024-10-30

## [1.15](https://github.com/coralnet/coralnet/tree/1.15)

Production: 2024-10-23

- New migrations to run for: `annotations`, `events`, `vision_backend`.
  - Before restarting the web server, run everything except annotations 0027.
    - events 0004 took 1 minute in production. The rest finished very quickly.
  - annotations 0027 took about 3 hours in production. It seems okay to run while the web server's running, but running in a transaction is a bit risky because we might overwrite new values from new classifications made during the migration. So for production, we ended up running the migration code in shell instead of with `manage.py migrate`, and faked the migration itself with `--fake`.
- Ensure the cached label details are updated before restarting the production web server. Otherwise, visiting the label_main pages will get errors.
  - To do this, run the following in manage.py shell:
    ```python
    from labels.utils import cacheable_label_details
    from lib.utils import context_scoped_cache
    with context_scoped_cache():
        cacheable_label_details.update()
    ```
  - This took 13 minutes in production.
- The new `CORALNET_1_15_DATE` setting must be specified for production, and may have to be specified more accurately in other envs.

## [1.14](https://github.com/coralnet/coralnet/tree/1.14)

Production: 2024-10-15

- Updates to required packages:
  - Django `>=4.1.9,<4.2` -> `>=4.2.16,<5.0`
  - django-environ 0.10.0 -> `@git+https://github.com/coralnet/django-environ.git@0.11.2+coralnet`
  - django-guardian 2.4.0 -> `@git+https://github.com/StephenChan/django-guardian.git@2.4.0+coralnet`
  - django-registration 3.3 -> 3.4
  - djangorestframework 3.14.0 -> 3.15.2
  - django-reversion 5.0.4 -> 5.1.0
  - django-storages 1.13.2 -> django-storages\[s3\] 1.14.4
  - easy-thumbnails `@git+https://github.com/StephenChan/easy-thumbnails.git@master` -> `@git+https://github.com/StephenChan/easy-thumbnails.git@2.9+coralnet`
  - tqdm 4.65.0 -> 4.66.5
  - gunicorn `>=20.1.0,<20.2` -> 23.0.0 (for production)
  - pytz can now be uninstalled, since djangorestframework no longer depends on it.
- New migrations to run for: `authtoken` (from djangorestframework), `jobs`. Runtime was 2 minutes in production.

## [1.13.1](https://github.com/coralnet/coralnet/tree/1.13.1)

Production: 2024-06-24

## [1.13](https://github.com/coralnet/coralnet/tree/1.13)

Production: 2024-05-23

- New migrations to run for `annotations`, `calcification`, `images`, `jobs`, `sources`, `vision_backend`. Runtime was 5 minutes in production.

## [1.12.1](https://github.com/coralnet/coralnet/tree/1.12.1)

Production: 2024-04-13

## [1.12](https://github.com/coralnet/coralnet/tree/1.12)

Production: 2024-04-12

- New package to install: django-huey>=1.1.2,<1.2
- Updates to required packages:
  - pyspacer 0.8.0 -> 0.9.0
  - Pillow 10.2.0 -> 10.3.0
  - django-markdownx `==4.0.2` -> `>=4.0.7,<4.1`
- New migrations to run for `jobs`.

## [1.11.1](https://github.com/coralnet/coralnet/tree/1.11.1)

Production: 2024-03-08

## [1.11](https://github.com/coralnet/coralnet/tree/1.11)

Production: 2024-01-29

- Updates to required packages:
  - Pillow 10.1.0 -> 10.2.0
  - pyspacer 0.7.0 -> 0.8.0

## [1.10](https://github.com/coralnet/coralnet/tree/1.10)

Production: 2024-01-14

- New migrations to run for `vision_backend`. Runtime should be less than 5 minutes in production. As noted in migration 0021's comments, non-production environments may want to take manual migration steps if their situations differ from production.

## [1.9.1](https://github.com/coralnet/coralnet/tree/1.9.1)

Production: 2024-01-09

## [1.9](https://github.com/coralnet/coralnet/tree/1.9)

Production: 2024-01-08

- Updates to required packages:
  - pyspacer 0.6.1 -> 0.7.0

### Notes

1.5's logging regression has been fixed. Unit-test console output is now clean, and logging statements from all project apps and pyspacer are now logged to `coralnet.log` and `coralnet_debug.log`.

## [1.8.1](https://github.com/coralnet/coralnet/tree/1.8.1)

Production: 2023-12-02

- New migration to run for `images`.

## [1.8](https://github.com/coralnet/coralnet/tree/1.8)

Production: 2023-11-27

- New migration to run for `vision_backend`.
- New package to install: diskcache 5.6.3
- Clear the current contents of the Django cache folder (`<SITE_DIR>/tmp/django_cache` by default). The format of cache files saved to this directory will be different from before.
- The `update_label_details` periodic-job should be run at least once to compute labels' annotation counts and popularities. This could take 1.5 hours with production amounts of data.

## [1.7.4](https://github.com/coralnet/coralnet/tree/1.7.4)

Production: 2023-11-20

## [1.7.3](https://github.com/coralnet/coralnet/tree/1.7.3)

Production: 2023-11-20

- New migration to run for `jobs`.

## [1.7.2](https://github.com/coralnet/coralnet/tree/1.7.2)

Production: 2023-11-19

## [1.7.1](https://github.com/coralnet/coralnet/tree/1.7.1)

Production: 2023/11/18-19

- New migration to run for `jobs`. If `api_core` 0004 runs into issues, try running the new `jobs` 0011 migration first.

## [1.7](https://github.com/coralnet/coralnet/tree/1.7)

Production: 2023/11/18 (updated from 1.1)

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