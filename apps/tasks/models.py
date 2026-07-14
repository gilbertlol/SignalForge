# Work-item / assignment models for humans and AI agents are added in
# GOR-237 (human and AI operator execution system). This app is
# registered now so its migrations state and service structure exist
# from the start of the project.
#
# Note: this app holds business work-item models, not Celery task
# definitions — those live in each app's own `tasks.py` module per
# Django/Celery convention (see apps/core/tasks.py).
