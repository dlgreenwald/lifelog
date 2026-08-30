"""Run alembic migrations as a standalone script.

Called by entrypoint.sh before uvicorn starts.
"""

from alembic.config import Config
from alembic import command


def run_migrations():
    alembic_cfg = Config("alembic.ini")
    command.upgrade(alembic_cfg, "head")
    print("[MIGRATE] Migrations applied successfully")


if __name__ == "__main__":
    run_migrations()
