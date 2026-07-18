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
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.workspace.service import WorkspaceService
from nowa_crm.ui.main_window import MainWindow
from nowa_crm.ui.login import LoginDialog, SetupDialog
from nowa_crm.ui.theme import THEME


def build_services(session=None):
    db = Database(database_path()); db.migrate(); events = EventBus()
    actor = session.username if session else getpass.getuser()
    customers=CustomerService(db,events); proposals=ProposalService(db)
    return db, customers, proposals, VaultService(db, data_dir() / "vault.key", actor, session), OperationsService(db), WorkspaceService(db,proposals,actor)


def main() -> int:
    app = QApplication(sys.argv); app.setStyleSheet(THEME)
    db, _, _, _, _, _ = build_services(); auth=AuthService(db)
    if not auth.has_users() and SetupDialog(auth).exec()!=QDialog.Accepted: return 0
    login=LoginDialog(auth)
    if login.exec()!=QDialog.Accepted or not login.session: return 0
    _, customers, proposals, vault, operations, workspace = build_services(login.session); window = MainWindow(customers, proposals, vault, operations, workspace); window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
