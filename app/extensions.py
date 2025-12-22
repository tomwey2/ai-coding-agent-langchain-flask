# This file serves as a central place to initialize Flask extensions.
#
# By creating extension objects here (e.g., `db`, `scheduler`) but not yet
# binding them to a specific Flask app, we can avoid circular import issues.
#
# For example, the main app file (main.py) and the models file (models.py) both
# need to import the `db` object. If `db` were created in `main.py`, `models.py`
# couldn't import it without creating a circular dependency.
#
# The extensions are bound to the app instance within the `create_app` factory
# function using the `.init_app()` method.

from flask_apscheduler import APScheduler
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
scheduler = APScheduler()
