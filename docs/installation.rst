Installation
============


PostgreSQL installation
-----------------------

Download and install the PostgreSQL server/core, 10.x. 32 or 64 bit shouldn't matter.

- On Linux, the package will probably be ``postgresql-10``.
- During the setup process, make sure you keep track of the root password.

Locate and open the client program that came with PostgreSQL. Windows has pgAdmin, while Linux should have the command-line ``postgresql-client`` or the GUI pgAdmin as options (may be distributed separately).

Using the client program, check that you can connect to the PostgreSQL server.


Database setup
--------------

Connect to the PostgreSQL server as the ``postgres`` or ``master`` user.

Create another user for the Django application to connect as. We'll say the user's called ``django``. Ensure ``django`` has permission to create databases (this is for running unit tests).

Create a database; we'll say it's called ``coralnet``. Owner = ``django``, Encoding = UTF8 (`Django says so <https://docs.djangoproject.com/en/dev/ref/databases/#optimizing-postgresql-s-configuration>`__). Defaults for other options should be fine.

Make sure that ``django`` has USAGE and CREATE privileges in the ``coralnet`` database's ``public`` schema.

Optimization recommended by Django: set some default parameters for database connections. `See the docs page <https://docs.djangoproject.com/en/dev/ref/databases/#optimizing-postgresql-s-configuration>`__. Can either set these for the ``django`` user with ``ALTER_ROLE``, or for all database users in ``postgresql.conf``.

Guide for pgAdmin 4
^^^^^^^^^^^^^^^^^^^

To create the user: Right-click Login/Group Roles, Create -> Login/Group Role..., Name = ``django``. Go to Definition tab and add password. Go to Privileges tab, Yes on "Can login?", Yes on "Create databases?". Save.

To add privileges: Expand the ``coralnet`` database, expand ``Schemas``, right click the ``public`` schema, Properties..., Security tab. Ensure there's a row with Grantee ``django`` and Privileges ``UC``.

``ALTER_ROLE`` method: Right click the ``django`` Login Role, Properties..., Parameters tab. Use the + button to add an entry. Database = ``coralnet``, Name and Value = whatever is specified in that Django docs link.

Notes
^^^^^

- When you create the ``coralnet`` database, it'll have ``public`` privileges by default. This means that every user created in that PostgreSQL installation has certain privileges by default, such as connecting to that database. `Related SO thread <http://stackoverflow.com/questions/6884020/why-new-user-in-postgresql-can-connect-to-all-databases>`__. This shouldn't be an issue as long as there are no PostgreSQL users with insecure passwords.

- A Django 1.7 release note says: "When running tests on PostgreSQL, the USER will need read access to the built-in postgres database." This doesn't seem to be a problem by default, probably due to the default ``public`` privileges described above.


Git
---
Git clone this repository.

If you're going to make any contributions:

- Create an SSH key on your machine for your user profile, and add the public part of the key on your GitHub settings. See `GitHub's instructions <https://help.github.com/articles/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent/>`__.

- Don't forget to set your Git username and email for this repository, so they show up in your commits.


Python
------
This project uses the latest Python 3.6.x, so download and install that.

Since this project has many third-party dependencies, and may require specific versions of those dependencies, it's highly recommended to use something like virtualenv to keep those dependencies separate from other Python projects.


.. _virtualenv:

Virtualenv
^^^^^^^^^^
Install virtualenv: ``pip install virtualenv`` (Be sure that you're using the ``pip`` from the Python installation you're using for CoralNet.)

``cd`` to somewhere outside of the ``coralnet`` Git repo. For example, you could go one directory up from the repo.

Create a virtual environment, making sure it uses your preferred Python version: ``virtualenv -p <path to python> <name of new virtualenv directory>`` (Again, find the ``virtualenv`` executable in the same directory as your python/pip executables.)

Activate your virtualenv: ``source <path to virtualenv you created>/bin/activate`` on Linux, ``<path to virtualenv you created>/Scripts/activate`` on Windows.

You should ensure that your virtual environment is activated when installing Python packages or running Django management commands for the CoralNet project. From here on out, these instructions will assume you have your virtual environment (also referred to as virtualenv) activated.


.. _python-packages:

Python packages
---------------
With your virtualenv activated, run ``pip install -r requirements/local.txt`` to install the packages. Note that this will install the listed packages as well as any dependencies those packages might have.

A few package/OS combinations may need additional steps:

- ``Pillow`` on Linux

  - You'll get errors if you don't have development packages for JPEG and PNG support:

    - libjpeg. For supported versions of libjpeg, see the `Pillow docs <https://pillow.readthedocs.io/en/latest/installation.html>`__. Check available versions in Ubuntu with ``apt-cache pkgnames | grep libjpeg``. Again, you'll want development libraries; for example, libjpeg version 8 in Ubuntu is ``libjpeg8-dev``.

    - zlib (PNG support). In Ubuntu, the dev library should be ``zlib1g-dev``.

  - There are also other packages that support optional functionality in Pillow. See the `Pillow docs <https://pillow.readthedocs.io/en/latest/installation.html>`__.

- ``scikit-learn`` on Linux

  - Requires g++: ``sudo apt install g++`` on Ubuntu

  - You may see "ERROR: Failed building wheel for scikit-learn", followed by an attempt to install using ``setup.py install``. If the latter attempt succeeds, then scikit-learn should be good to go.

- ``scipy`` on Windows

  - Installing SciPy with the requirements file will fail for two reasons. First, NumPy needs to be installed as NumPy+MKL, and the binary for that isn't on PyPI. Second, even after getting the NumPy install right, installing SciPy with pip fails for some reason (the first problem is ``libraries openblas not found in [ ... ] NOT AVAILABLE``).

  - What to do: First install NumPy+MKL and then SciPy manually using the .whl files here: http://www.lfd.uci.edu/~gohlke/pythonlibs/ Be sure to pick the appropriate .whl depending on whether your Python is 32 or 64 bit. To install a .whl, run ``pip install <path to .whl>``. Then run the requirements file to install the rest of the packages.

- ``torch`` and ``torchvision`` on Windows

  - Confirm your CUDA version if you have a GPU that supports it. For example, NVIDIA Control Panel > Help > System Information > Components tab should have this info.

  - Head to the `PyTorch website <https://pytorch.org/>`__ and find the install or getting started page. There are a few possible ways to try to get the appropriate .whl files depending on your OS, CUDA version, and target torch / torchvision versions. For old versions, either try the "install previous versions" link, or head directly to https://download.pytorch.org/whl/torch_stable.html and find the .whl files that most closely match your environment. Download the .whl files and run ``pip install <path to .whl>`` on each.

  - To import torchvision 0.5.0 without getting a "The program can't start because avcodec-58.dll is missing from your computer." error dialog, download the shared version (not static) of ffmpeg and add its ``bin`` directory to your PATH environment variable. (`Source <https://github.com/pytorch/vision/issues/1877>`__)

If you think you messed up and want to undo a pip installation, use ``pip uninstall <package-name>``.

From now on, whenever you need to get your packages up to date, activate your virtualenv and rerun ``pip install -r requirements/<name>.txt``.


Django settings module
----------------------
Look under ``project/config/settings``.

- If you are setting up a development server, use one of the dev-specific settings modules (such as ``dev_stephen.py``) or make your own. The module should include:

  - An import of ``base_devserver``
  - An import of either ``storage_local`` or ``storage_s3``, depending on whether you want to store media files locally or in an S3 bucket. Local storage works fine for most functionality, but the vision backend requires S3.
  - Any settings values you want to customize for your environment specifically

By default, Django expects the settings to be in a ``settings.py`` at the project root, so we have to tell it otherwise. One way is with the ``DJANGO_SETTINGS_MODULE`` environment variable. Set this variable to ``config.settings.<module name>``, where ``<module name>`` is ``dev_stephen``, ``dev_oscar``, etc.

- For example, in Linux (bash and most other shells): ``export DJANGO_SETTINGS_MODULE=config.settings.dev_stephen``


secrets.json
------------
Some settings like passwords shouldn't be committed to the repo. We keep these settings in an un-committed ``project/config/settings/secrets.json`` file. Create this file and fill it with anything that the settings module obtains with ``get_secret()``. For example::

  {
    "DATABASES_PASSWORD": "correcthorsebatterystaple",
    "DATABASES_HOST": "",
    "DATABASES_PORT": ""
  }

If you're missing any secret settings in ``secrets.json``, you'll get an ``ImproperlyConfigured`` error when running any ``manage.py`` commands.

Check your settings module (and anything it imports from, such as ``base.py``) for details on the format of each required secret setting.


Creating necessary directories
------------------------------
Certain file-creation parts of the project code may trigger an error such as ``No such file or directory`` when the destination directory doesn't already exist. This behavior should probably be fixed at some point, but in the meantime, you'll need to create at least the following directories:

- ``<SITE_DIR>/log``
- ``<SITE_DIR>/tmp``
- ``<MEDIA_ROOT>/unittests`` (local-machine storage only)


Running the unit tests
----------------------
At this point, you should be ready to run the unit test suite to check if everything is working so far.

Run ``python manage.py test``. Test failures will be shown as F, and errors will be shown as E.

If you want to run a subset of the tests, you can use ``python manage.py test <app_name>``, or ``python manage.py test <app_name>.<module>.<TestClass>``.


Django migrations
-----------------
Run ``python manage.py migrate``. If Django's auth system asks you to create a superuser, then do that.


Running the web server
----------------------
Ensure your virtualenv is activated, and run ``python manage.py runserver`` from the ``project`` directory.

Navigate to your localhost web server, e.g. ``http://127.0.0.1:8000/``, in your browser.


Testing that it works
---------------------
Register and activate a user using the website's views. If you're using the development server, you should see the activation email in the console running Django.

Try creating a source, uploading images, making a labelset, making annotations, checking annotation history, and browsing patches. Test any other pages that come to mind.

If you don't have a superuser yet, use ``python manage.py createsuperuser`` to create one. Log in as a superuser and try checking out the admin interface at ``<site domain>/admin/``.


PyCharm configuration
---------------------
Here are some tips for developing and running the website with the PyCharm IDE (optional, but recommended for site development). These instructions refer to PyCharm 2.6.3 (2012/02/26), so some points may be out of date.

How to make PyCharm find everything:

- Make ``coralnet`` your PyCharm project root.

- Go to the Django Support settings and use ``project`` as the Django project root. Also set your Manage script (``manage.py``) and Settings file accordingly.

- Go to the Project Interpreter settings and select the Python within your virtualenv (should be under ``Scripts``). This should make PyCharm detect our third-party Python apps.

- Go to the Project Structure settings and mark ``project`` as a Sources directory (`Help <https://www.jetbrains.com/help/pycharm/2016.1/configuring-folders-within-a-content-root.html>`__). This is one way to make PyCharm recognize imports of our apps, such as ``annotations.models``. (There may be other ways.)

- Go to the Python Template Languages settings. Under Template directories, add one entry for each ``templates`` subdirectory in the repository.

How to make a Run Configuration that runs ``manage.py runserver`` from PyCharm:

- Run -> Edit Configurations..., then make a new configuration under "Django server".

- Add an environment variable with Name ``DJANGO_SETTINGS_MODULE`` and Value ``config.settings.<name>``, with <name> being ``local``, ``dev_stephen``, etc. [#pycharmenvvar]_

- If on Windows, set the PATH environment variable in the run configuration, to include shared ffmpeg (to avoid the avcodec-58.dll error). There doesn't seem to be a way to add to the existing PATH, but overriding the old PATH with nothing but ffmpeg seems to be OK.

- Ensure that "Python interpreter" has the Python from your virtualenv.

.. [#pycharmenvvar] Not sure why this is needed when we specify the settings module in Django Support settings, but it was needed in my experience. -Stephen


Running the web server with DEBUG = False
-----------------------------------------
Sometimes you need to run the server with ``DEBUG = False`` in your settings to test something - for example, the 404 and 500 error pages. Running the server like this requires a couple of extra steps.

- Define ``ALLOWED_HOSTS`` in your settings, otherwise runserver gets a CommandError. A value of ``['*']`` should work for development purposes.

- To serve media files, define a ``MEDIA_URL`` in your settings; for example, ``http://127.0.0.1:8070/``. Then in a terminal/command window, run: ``python -m http.server 8070``

- To serve static files, define a ``STATIC_URL`` in your settings; for example, ``http://127.0.0.1:8080/``. Then in a terminal/command window, run: ``python -m http.server 8080``

  - Any time static files (CSS, Javascript, etc.) are added or changed, run ``python manage.py collectstatic`` to copy those added/changed static files to STATIC_ROOT. Do ``python manage.py collectstatic --clear`` instead if you think there's some obsolete static files that can be cleaned up.
