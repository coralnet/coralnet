Installation
============


PostgreSQL installation
-----------------------

Download and install the PostgreSQL server/core, 14.x.

- On Linux, the package will probably be ``postgresql-14``.
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


Git
---
Git clone this repository.

If you're going to make any contributions:

- Create an SSH key on your machine for your user profile, and add the public part of the key on your GitHub settings. See `GitHub's instructions <https://help.github.com/articles/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent/>`__.

- Don't forget to set your Git username and email for this repository, so they show up in your commits.


Python
------
This project uses Python 3.10.x, so download and install that.

Since this project has many third-party dependencies, and requires specific versions of those dependencies, it's highly recommended to install dependencies in some kind of separate environment rather than being tied to the Python installation (which you may be using for other projects besides CoralNet). Tools such as venv, virtualenv, or conda can achieve this.


.. _virtual_environment:

Virtual environment
^^^^^^^^^^^^^^^^^^^
This section will cover venv, since venv comes with Python without needing an extra installation step. However, virtualenv, conda, or other tools should work too.

Create a virtual environment at a location of your choice: ``python -m venv /path/to/myenv``. Make sure to pick a location outside of the ``coralnet`` Git repo. For example, you could go one directory up from the repo.

Activate your environment: ``source /path/to/myenv/bin/activate`` on Linux, ``C:/path/to/myenv/Scripts/activate`` on Windows.

You should ensure that your virtual environment is activated when installing Python packages or running Django management commands for the CoralNet project. From here on out, these instructions will assume you have your virtual environment activated.


.. _python-packages:

Python packages
---------------
With your virtual environment activated, run ``pip install -r requirements/local.txt`` to install the packages. Note that this will install the packages listed/included in that file as well as any dependencies those packages might have.

If you're also working on the PySpacer codebase, or otherwise need a PySpacer version more recent than what's on PyPI, you'll probably want to specify an `editable install <https://pip.pypa.io/en/stable/topics/local-project-installs/>`__ of PySpacer: ``pip install -e path/to/local/spacer``

- The cleanest way to use this would be to do the -e spacer install first, then install other packages with the -r command above.

- Note that any CoralNet pull request you make might not pass in GitHub's CI (GitHub Actions) until PySpacer is updated on PyPI.

If you think something messed up and you want to undo a pip installation, use ``pip uninstall <package-name>``.

From now on, whenever you need to get your packages up to date, activate your virtual environment and run ``pip install -U -r requirements/<name>.txt``.


Settings
--------
Most configuration for the Django project is defined in the version-controlled file ``project/config/settings.py``. However, some configuration details are unique to each installation (such as passwords). There are two ways to specify these settings:

1. Create an un-committed ``.env`` file at the root of the repository (in ``coralnet``, on the same level as ``project``). Consult the example file ``.env.dist`` as a guide on how to write the contents of ``.env``. Here's an example snippet:

   .. code-block::

     SETTINGS_BASE=dev-local
     DATABASE_NAME=coralnet
     DATABASE_USER=django

2. Set environment variables. Each variable should be prefixed with ``CORALNET_`` in this case. Example commands to set the variables:

   .. code-block::

     export CORALNET_SETTINGS_BASE='dev-local'
     export CORALNET_DATABASE_NAME='coralnet'
     export CORALNET_DATABASE_USER='django'

If you're missing any expected settings, you should get an ``ImproperlyConfigured`` error when running any ``manage.py`` commands.


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

Note: running the whole test suite with S3 storage can take a long time. As of April 2021, one particular development machine takes 7 minutes to run the test suite with local storage, and 2 hours 40 minutes with S3 storage.


Django migrations
-----------------
Run ``python manage.py migrate``. If Django's auth system asks you to create a superuser, then do that.


Running the web server
----------------------
Ensure your virtual environment is activated, and run ``python manage.py runserver`` from the ``project`` directory.

Navigate to your localhost web server, e.g. ``http://127.0.0.1:8000/``, in your browser.


Testing that it works
---------------------
Register and activate a user using the website's views. If you're using the development server, you should see the activation email in the console running Django.

Try creating a source, uploading images, making a labelset, making annotations, checking annotation history, and browsing patches. Test any other pages that come to mind.

If you don't have a superuser yet, use ``python manage.py createsuperuser`` to create one. Log in as a superuser and try checking out the admin interface at ``<site domain>/admin/``.


PyCharm configuration
---------------------
Here are some tips for developing and running the website with the PyCharm IDE (optional, but recommended for site development). These instructions are up to date as of PyCharm 2023.1.2.

Initial setup:

- Open PyCharm, File -> New Project, and select Django. The PyCharm project's root should be at the repository root, ``coralnet``. The Python interpreter should be the Python executable in your virtual environment.

- In the directory tree sidebar, right-click the ``project`` folder, and select Mark Directory as -> Sources Root.

Make a Run Configuration that runs ``manage.py runserver`` from PyCharm:

- Run -> Edit Configurations..., then make a new configuration under "Django server".  Add an environment variable with Name ``DJANGO_SETTINGS_MODULE`` and Value ``config.settings``.

- This Run Configuration should let you use ``runserver`` from PyCharm. You can Run it normally, or you can Debug it to use breakpoints and inspect values.

Go to Settings -> Languages & Frameworks -> Django, select the coralnet project, and ensure that ``config/settings.py`` is set as the settings file. This should enable PyCharm to recognize template-tag loading and template paths throughout the project.

- If template paths still aren't recognized, there's another way: right-click a templates folder in the tree view and select Mark Directory as -> Template Folder.


Running the web server with DEBUG = False
-----------------------------------------
Sometimes you want to run your development server with the ``DEBUG = False`` setting to test something - for example, the 404 and 500 error pages.

There is a section of ``.env.dist`` which explains how to set this up, so follow the explanations there.


Linting
-------
The coralnet repo has pre-commit hooks available, although they're not consistently used by all devs yet. To use them, run ``pre-commit install`` to activate after installing the packages in ``local.txt``. Linting will run automatically on ``git commit``.
