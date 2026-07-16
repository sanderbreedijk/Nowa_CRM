from __future__ import annotations

import getpass
import sys

from PySide6.QtWidgets import QApplication, QDialog

from nowa_crm.core.database import Database
from nowa_crm.core.auth import AuthService
from nowa_crm.core.events import EventBus
from nowa_crm.core.paths import data_dir, database_path
from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.ui.main_window import MainWindow
from nowa_crm.ui.login import LoginDialog, SetupDialog
from nowa_crm.ui.theme import THEME


def build_services(session=None):
    db = Database(database_path()); db.migrate(); events = EventBus()
    actor = session.username if session else getpass.getuser()
    return db, CustomerService(db, events), ProposalService(db), VaultService(db, data_dir() / "vault.key", actor, session)


def main() -> int:
    app = QApplication(sys.argv); app.setStyleSheet(THEME)
    db, _, _, _ = build_services(); auth=AuthService(db)
    if not auth.has_users() and SetupDialog(auth).exec()!=QDialog.Accepted: return 0
    login=LoginDialog(auth)
    if login.exec()!=QDialog.Accepted or not login.session: return 0
    _, customers, proposals, vault = build_services(login.session); window = MainWindow(customers, proposals, vault); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
