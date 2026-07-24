from __future__ import annotations

import json

from nowa_crm.core.database import Database
from nowa_crm.core.paths import data_dir, database_path
from nowa_crm.core.remote_database import RemoteDatabase
from nowa_crm.core.postgres_database import PostgresDatabase
from nowa_crm.core.secret_store import LocalSecretStore


def active_database():
    config=data_dir()/"multiuser.json"
    if config.exists():
        try:
            settings=json.loads(config.read_text(encoding="utf-8"))
            if settings.get("mode")=="postgres":
                password=LocalSecretStore(data_dir()).unprotect(settings.get("postgres_password",""))
                return PostgresDatabase(settings["host"],int(settings["port"]),settings["database"],
                                        settings["postgres_user"],password,settings.get("sslmode","prefer"))
            if settings.get("mode")=="central":
                return RemoteDatabase(settings["host"],int(settings["port"]),settings["access_key"],bool(settings.get("tls",True)))
        except (OSError,ValueError,KeyError,TypeError):
            pass
    return Database(database_path())
