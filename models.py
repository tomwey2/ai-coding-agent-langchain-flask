from extensions import db


class AgentConfig(db.Model):
    __tablename__ = "agent_config"

    id = db.Column(db.Integer, primary_key=True)
    task_app_base_url = db.Column(db.String(255), nullable=False)
    api_token = db.Column(db.String(255), nullable=True)
    polling_interval_seconds = db.Column(db.Integer, nullable=False, default=60)
    is_active = db.Column(db.Boolean, nullable=False, default=False)

    def __init__(
        self,
        task_app_base_url=None,
        api_token=None,
        polling_interval_seconds=60,
        is_active=False,
        **kwargs,
    ):
        super(AgentConfig, self).__init__(**kwargs)
        self.task_app_base_url = task_app_base_url
        self.api_token = api_token
        self.polling_interval_seconds = polling_interval_seconds
        self.is_active = is_active

    def __repr__(self):
        return f"<AgentConfig {self.id}>"
