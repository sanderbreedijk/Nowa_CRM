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
        except (OSError,ValueError,TypeError) as exc:
            raise ConnectionError(f"De database-instellingen kunnen niet worden gelezen: {exc}") from exc
        mode=settings.get("mode","local")
        if mode=="postgres":
            try:
                password=LocalSecretStore(data_dir()).unprotect(settings.get("postgres_password",""))
                if not password:
                    raise ValueError("het lokaal opgeslagen PostgreSQL-wachtwoord ontbreekt")
                return PostgresDatabase(settings["host"],int(settings["port"]),settings["database"],
                                        settings["postgres_user"],password,settings.get("sslmode","prefer"))
            except (OSError,ValueError,KeyError,TypeError) as exc:
                raise ConnectionError(
                    "PostgreSQL is ingesteld, maar de verbinding kan op deze computer niet worden geopend "
                    f"({exc}). NOWA CRM schakelt niet over op een lege lokale database.") from exc
        if mode=="central":
            try:
                return RemoteDatabase(settings["host"],int(settings["port"]),settings["access_key"],bool(settings.get("tls",True)))
            except (OSError,ValueError,KeyError,TypeError) as exc:
                raise ConnectionError(f"De centrale database-instellingen zijn ongeldig: {exc}") from exc
    return Database(database_path())

