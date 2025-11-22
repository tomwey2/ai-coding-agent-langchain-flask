import os

# Best practice: Load secrets from environment variables
# For simplicity in this phase, we use a default secret key.
SECRET_KEY = os.environ.get("SECRET_KEY", "a-default-secret-key-for-development")

# Database configuration
basedir = os.path.abspath(os.path.dirname(__file__))
SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///" + os.path.join(
    basedir, "instance", "agent.db"
)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Scheduler configuration
SCHEDULER_API_ENABLED = True
