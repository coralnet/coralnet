Semantic versioning
===================


CoralNet versions serve as landmarks to improve communication between devs about new changes and associated upgrade steps. These landmarks can also help with troubleshooting issues.

Versions take on the form A.B.C, where:

- A is the **major version**. Updating this indicates an overall big change to CoralNet, usually including major user-visible changes such that it makes sense to mention the version bump in a blog post.

  For example, we announced CoralNet 1.0 (or 1.0.0) when we introduced the Deploy API and EfficientNet extractor, alongside major internal changes done in that round (AWS Batch / Python 3).

  Possible reasons for a version 2.0(.0) would include an expanded API, multiple labels per point, some form of orthomosaic support, semantic segmentation, etc.

- B is the **minor version**. Updating this indicates that a CoralNet environment (production/staging or development) needs to do something other than ``git pull`` and ``manage.py collectstatic`` to update to that point of the repo. For example, updating a package version, running DB migrations, or specifying new settings.

  In general, this could be advanced once per pull request which involves such steps for updating, but there may be exceptions. For example, one minor version for back-to-back related PRs, or multiple minor versions for a single PR with a tricky installation (like `PR #387 <https://github.com/coralnet/coralnet/pull/387>`__).

- C is the **patch version**. A new patch version indicates one of two things: 1) any update that doesn't meet the criteria for A or B, but is still worth marking as a version for one reason or another; or 2) a hotfix for a major/minor version that was just released in a broken state.

  Patch versions can be used as often or as scarcely as we see fit; we may frequently have smaller PRs which don't have any version bump at all, particularly if we're not in a rush to get the changes into production.

Note that the versioning system for pluggable apps tends to be different; in particular, the criteria for B are often considered worthy of a major version. But the system above feels better optimized for CoralNet; this is an end-user app, not a pluggable one.

A dev looking to update an environment can:

1. Identify the version their environment is on, and the version they want to update to.

2. Update the current branch to the desired version tag, with something like ``git rebase <version>`` or ``git pull origin <version>``.

3. Follow the instructions in the changelog from the old version to the new version. No need to dig through the individual PRs/commit details.
