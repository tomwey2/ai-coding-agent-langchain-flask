from extensions import db


class AgentConfig(db.Model):
    __tablename__ = "agent_config"

    id = db.Column(db.Integer, primary_key=True)
    # Generic Task System Fields
    task_system_type = db.Column(
        db.String(50), nullable=False, default="CUSTOM"
    )  # e.g., "TRELLO", "JIRA", "CUSTOM"
    system_config_json = db.Column(
        db.Text, nullable=True
    )  # JSON blob for credentials, IDs, etc.

    # Existing Fields
    repo_type = db.Column(
        db.String(50), nullable=False, default="GITHUB"
    )  # e.g., "GITHUB", "BITBUCKET"
    github_repo_url = db.Column(
        db.String(200),
        default="https://github.com/tomwey2/calculator-spring-docker-jenkins.git",
    )
    polling_interval_seconds = db.Column(db.Integer, nullable=False, default=60)
    is_active = db.Column(db.Boolean, nullable=False, default=False)

    def __init__(self, **kwargs):
        super(AgentConfig, self).__init__(**kwargs)

    def __repr__(self):
        return f"<AgentConfig {self.id}>"
