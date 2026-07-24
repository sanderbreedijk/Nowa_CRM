from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QDialog

from nowa_crm.core.database_factory import active_database
from nowa_crm.core.auth import AuthService
from nowa_crm.core.events import EventBus
from nowa_crm.core.paths import data_dir
from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.modules.operations.service import OperationsService
from nowa_crm.modules.workspace.service import WorkspaceService
from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.telephony.service import TelephonyService
from nowa_crm.ui.main_window import MainWindow
from nowa_crm.ui.login import LoginDialog, SetupDialog
from nowa_crm.ui.theme import THEME
from nowa_crm.ui.icons import app_icon
from nowa_crm.modules.multiuser.service import MultiUserService


def _configure_packaged_certificates() -> None:
    """Gebruik de hernoemde openbare CA-bundel zonder privé-certificaten toe te staan."""
    if not getattr(sys,"frozen",False):
        return
    root=Path(getattr(sys,"_MEIPASS",Path(sys.executable).resolve().parent))
    certificate=root/"certifi"/"cacert.crt"
    if not certificate.is_file():
        return
    os.environ["SSL_CERT_FILE"]=str(certificate)
    os.environ["REQUESTS_CA_BUNDLE"]=str(certificate)
    try:
        import certifi
        import certifi.core
        certifi.where=lambda: str(certificate)
        certifi.core.where=lambda: str(certificate)
    except ImportError:
        pass


def build_services(session=None):
    db = active_database(); db.migrate(); events = EventBus()
    actor = session.username if session else getpass.getuser()
    vault_key=data_dir() / ("central-vault.key" if getattr(db,"is_remote",False) else "vault.key")
    if getattr(db,"is_remote",False):
        key=db.vault_key()
        if not vault_key.exists() or vault_key.read_bytes()!=key:vault_key.write_bytes(key)
    customers=CustomerService(db,events); proposals=ProposalService(db)
    workspace=WorkspaceService(db,proposals,actor)
    return db, customers, proposals, VaultService(db, vault_key, actor, session), OperationsService(db), workspace, MailService(db,actor), TelephonyService(db,workspace,actor)


def _startup_phone(arguments: list[str]) -> str:
    if "--phone" in arguments:
        index=arguments.index("--phone")
        return arguments[index+1] if index+1<len(arguments) else ""
    for value in arguments:
        if value.startswith(("tel:","callto:")):return value.split(":",1)[1]
        if sum(ch.isdigit() for ch in value)>=6:return value
    return ""


def main() -> int:
    _configure_packaged_certificates()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv); app.setApplicationName("NOWA CRM"); app.setWindowIcon(app_icon()); app.setStyleSheet(THEME)
    try:db, _, _, _, _, _, _, _ = build_services()
    except ConnectionError as exc:
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None,"Centrale server niet bereikbaar",
            f"{exc}\n\nStart de servercomputer of herstel in multiuser.json tijdelijk mode naar local.")
        return 1
    multiuser=MultiUserService(db);server_settings=multiuser.settings()
    if not getattr(db,"is_remote",False) and server_settings.get("server_enabled"):
        try:multiuser.start_server("0.0.0.0",server_settings["port"],server_settings["access_key"])
        except OSError as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None,"Centrale server",f"De centrale databaseservice kon niet starten:\n{exc}")
    auth=AuthService(db)
    if not auth.has_users() and SetupDialog(auth).exec()!=QDialog.Accepted: return 0
    login=LoginDialog(auth)
    if login.exec()!=QDialog.Accepted or not login.session: return 0
    _, customers, proposals, vault, operations, workspace, mail, telephony = build_services(login.session); window = MainWindow(customers, proposals, vault, operations, workspace, mail, telephony); window.showMaximized()
    phone=_startup_phone(sys.argv[1:])
    if phone:window.handle_incoming_phone(phone)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

