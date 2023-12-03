Semantic versioning
===================


CoralNet versions serve as landmarks to improve communication, bookkeeping, and troubleshooting related to new changes and associated upgrade steps.

For bookkeeping, a new version should be released every time the production server's updated. For collaboration between devs, it may be useful to have additional releases to communicate significant changes and upgrade steps.

Significant upgrade steps should be listed in CHANGELOG.md. These include updating a package version, running database migrations, or specifying new settings. Basically anything other than ``git pull`` and ``manage.py collectstatic``.

Versions take on the form A.B.C, where:

- A is the **major version**. Updating this indicates an overall big change to CoralNet, usually including major user-visible changes such that it makes sense to mention the version bump in a blog post.

  For example, we announced CoralNet 1.0 (or 1.0.0) when we introduced the Deploy API and EfficientNet extractor, alongside major internal changes done in that round (AWS Batch / Python 3).

  Possible reasons for a version 2.0(.0) would include an expanded API, multiple labels per point, some form of orthomosaic support, semantic segmentation, etc.

- B is the **minor version**, and C is the **patch version**. There isn't a strict distinction between minor and patch, but in general, patch versions are just for small changes or fixes made shortly after a minor version.

There should be no more than one version release associated with a single pull request. Exceptions may be made when needed (like `PR #387 <https://github.com/coralnet/coralnet/pull/387>`__), but that generally indicates that a PR was too complex and should have been split up.

A dev looking to update an environment can:

1. Identify the version their environment is on, and the version they want to update to.

2. Update the current branch to the desired version tag, with something like ``git rebase <version>`` or ``git pull origin <version>``.

3. Follow the instructions in the changelog from the old version to the new version. No need to dig through the individual PRs/commit details.
