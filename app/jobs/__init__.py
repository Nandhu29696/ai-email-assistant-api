"""Background jobs. Importing this package registers every job function."""
from app.jobs import tasks  # noqa: F401  (registers jobs in app.jobs.queue.REGISTRY)
