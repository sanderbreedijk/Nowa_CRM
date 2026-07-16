from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.vault.service import VaultService
from nowa_crm.ui.dialogs import CustomerDialog, VaultDialog
from nowa_crm.core.updater import RELEASES_URL, UpdateService
from nowa_crm import __version__


class MainWindow(QMainWindow):
    def __init__(self, customers: CustomerService, proposals: ProposalService, vault: VaultService):
        super().__init__(); self.customers=customers; self.proposals=proposals; self.vault=vault
        self.setWindowTitle("NOWA CRM"); self.resize(1380,860)
        root=QWidget(); shell=QHBoxLayout(root); shell.setContentsMargins(0,0,0,0); sidebar=QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(230); nav=QVBoxLayout(sidebar)
        brand=QLabel("NOWA CRM"); brand.setObjectName("Brand"); nav.addWidget(brand); self.stack=QStackedWidget()
        pages=[("Overzicht",self._dashboard()),("Klanten",self._customer_page()),("Offertes",self._proposal_page()),("IT Kluis",self._vault_page()),("Mail",self._placeholder("Mail","Klantmails en sjablonen worden hier als zelfstandige module aangesloten.")),("Telefonie",self._placeholder("Coligo telefonie","Inkomende nummers worden hier straks direct aan klanten gekoppeld.")),("Updates",self._update_page())]
        self.nav_group=QButtonGroup(self); self.nav_group.setExclusive(True)
        for i,(title,page) in enumerate(pages):
            b=QPushButton(title); b.setObjectName("Nav"); b.setCheckable(True); b.setChecked(i==0); self.nav_group.addButton(b,i); b.clicked.connect(lambda _,x=i:self._show(x)); nav.addWidget(b); self.stack.addWidget(page)
        nav.addStretch(); shell.addWidget(sidebar); shell.addWidget(self.stack,1); self.setCentralWidget(root); self.refresh_all()

    def _show(self,index): self.stack.setCurrentIndex(index); self.refresh_all()
    def _page(self,title,subtitle=""):
        page=QWidget(); box=QVBoxLayout(page); head=QLabel(title); head.setObjectName("Title"); box.addWidget(head)
        if subtitle: sub=QLabel(subtitle); sub.setObjectName("Subtitle"); box.addWidget(sub)
        return page,box
    def _placeholder(self,title,text):
        page,box=self._page(title,text); box.addStretch(); return page
    def _update_page(self):
        page,box=self._page("Updates",f"Geïnstalleerde versie: {__version__}")
        card=QFrame(); card.setObjectName("Card"); content=QVBoxLayout(card)
        self.update_status=QLabel("Controleer GitHub Releases op een nieuwe, geteste Windows-versie."); self.update_status.setWordWrap(True); content.addWidget(self.update_status)
        row=QHBoxLayout(); check=QPushButton("Controleren op updates"); check.setObjectName("Primary"); check.clicked.connect(self.check_for_updates); releases=QPushButton("Releases openen"); releases.clicked.connect(lambda:QDesktopServices.openUrl(QUrl(RELEASES_URL))); row.addWidget(check); row.addWidget(releases); row.addStretch(); content.addLayout(row); box.addWidget(card); box.addStretch(); return page
    def _dashboard(self):
        page,box=self._page("Goedemiddag","Uw centrale werkplek voor klanten, offertes en veilige service."); grid=QGridLayout(); self.kpis=[]
        for i,title in enumerate(("Klanten","Open offertes","Kluisitems")):
            card=QFrame(); card.setObjectName("Card"); c=QVBoxLayout(card); value=QLabel("0"); value.setObjectName("Kpi"); c.addWidget(value); c.addWidget(QLabel(title)); grid.addWidget(card,0,i); self.kpis.append(value)
        box.addLayout(grid); hint=QFrame(); hint.setObjectName("Card"); h=QVBoxLayout(hint); h.addWidget(QLabel("Slim voorbereid op groei")); h.addWidget(QLabel("Mail en Coligo-nummerherkenning worden via losse koppelingen toegevoegd zonder de CRM-kern te wijzigen.")); box.addWidget(hint); box.addStretch(); return page
    def _customer_page(self):
        page,box=self._page("Klanten","Eén betrouwbaar klantbeeld voor alle NOWA-modules."); row=QHBoxLayout(); self.customer_search=QLineEdit(); self.customer_search.setPlaceholderText("Zoek op naam, nummer, telefoon, e-mail of plaats…"); self.customer_search.textChanged.connect(self.refresh_customers)
        add=QPushButton("Nieuwe klant"); add.setObjectName("Primary"); add.clicked.connect(self.add_customer); edit=QPushButton("Bewerken"); edit.clicked.connect(self.edit_customer); row.addWidget(self.customer_search,1); row.addWidget(edit); row.addWidget(add); box.addLayout(row)
        self.customer_table=QTableWidget(0,6); self.customer_table.setHorizontalHeaderLabels(["Klantnummer","Naam","E-mail","Telefoon","Plaats","ID"]); self.customer_table.setColumnHidden(5,True); self.customer_table.horizontalHeader().setStretchLastSection(True); self.customer_table.doubleClicked.connect(self.edit_customer); box.addWidget(self.customer_table,1); return page
    def _proposal_page(self):
        page,box=self._page("Offertes","Versies en status overzichtelijk per klant beheren."); row=QHBoxLayout(); self.proposal_search=QLineEdit(); self.proposal_search.setPlaceholderText("Zoek offerte of klant…"); self.proposal_search.textChanged.connect(self.refresh_proposals); add=QPushButton("Nieuwe offerte"); add.setObjectName("Primary"); add.clicked.connect(self.add_proposal); row.addWidget(self.proposal_search,1); row.addWidget(add); box.addLayout(row)
        self.proposal_table=QTableWidget(0,7); self.proposal_table.setHorizontalHeaderLabels(["Nummer","Klant","Titel","Status","Revisie","Totaal","ID"]); self.proposal_table.setColumnHidden(6,True); self.proposal_table.horizontalHeader().setStretchLastSection(True); box.addWidget(self.proposal_table,1); return page
    def _vault_page(self):
        page,box=self._page("IT Kluis","Vind tijdens een klantgesprek snel het juiste gegeven; geheimen blijven standaard verborgen."); row=QHBoxLayout(); self.vault_search=QLineEdit(); self.vault_search.setPlaceholderText("Zoek klant, nummer, account, gebruikersnaam of domein…"); self.vault_search.textChanged.connect(self.refresh_vault); reveal=QPushButton("Tonen en kopiëren"); reveal.clicked.connect(self.reveal_secret); add=QPushButton("Nieuw kluisitem"); add.setObjectName("Primary"); add.clicked.connect(self.add_vault); row.addWidget(self.vault_search,1); row.addWidget(reveal); row.addWidget(add); box.addLayout(row)
        self.vault_table=QTableWidget(0,7); self.vault_table.setHorizontalHeaderLabels(["Klant","Klantnr.","Categorie","Omschrijving","Gebruikersnaam","URL","ID"]); self.vault_table.setColumnHidden(6,True); self.vault_table.horizontalHeader().setStretchLastSection(True); self.vault_table.doubleClicked.connect(self.reveal_secret); box.addWidget(self.vault_table,1); return page
    def _selected_id(self,table,col):
        row=table.currentRow(); item=table.item(row,col) if row>=0 else None; return int(item.text()) if item else None
    def add_customer(self):
        dlg=CustomerDialog(self)
        if dlg.exec():
            try:self.customers.create(*dlg.values()); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"Klant opslaan",str(e))
    def edit_customer(self,*_):
        cid=self._selected_id(self.customer_table,5)
        if not cid:return
        customer=self.customers.get(cid); dlg=CustomerDialog(self,customer)
        if dlg.exec():
            try:self.customers.update(cid,*dlg.values()); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"Klant opslaan",str(e))
    def add_proposal(self):
        customers=self.customers.search();
        if not customers: QMessageBox.information(self,"Offerte","Voeg eerst een klant toe."); return
        labels=[f"{c.customer_number} — {c.name}" for c in customers]; label,ok=QInputDialog.getItem(self,"Nieuwe offerte","Klant",labels,0,False)
        if not ok:return
        title,ok=QInputDialog.getText(self,"Nieuwe offerte","Titel")
        if ok:
            try:self.proposals.create(customers[labels.index(label)].id,title); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"Offerte",str(e))
    def add_vault(self):
        customers=self.customers.search()
        if not customers: QMessageBox.information(self,"IT Kluis","Voeg eerst een klant toe."); return
        dlg=VaultDialog(customers,self)
        if dlg.exec():
            try:self.vault.add(dlg.customer.currentData(),dlg.label.text(),dlg.username.text(),dlg.secret.text(),dlg.category.currentText(),dlg.url.text()); self.refresh_all()
            except Exception as e: QMessageBox.critical(self,"IT Kluis",str(e))
    def reveal_secret(self,*_):
        entry_id=self._selected_id(self.vault_table,6)
        if not entry_id: QMessageBox.information(self,"IT Kluis","Selecteer eerst een kluisitem."); return
        reason,ok=QInputDialog.getText(self,"Verificatie","Reden / wijze van klantverificatie")
        if not ok:return
        try:
            secret=self.vault.reveal(entry_id,reason); QApplication.clipboard().setText(secret); QMessageBox.information(self,"Veilig gekopieerd","Het gegeven staat 30 seconden op het klembord.")
            QTimer.singleShot(30000,lambda:self._clear_clipboard(secret))
        except Exception as e: QMessageBox.warning(self,"IT Kluis",str(e))
    def _clear_clipboard(self,secret):
        if QApplication.clipboard().text()==secret: QApplication.clipboard().clear()
    def check_for_updates(self):
        self.update_status.setText("GitHub wordt gecontroleerd…"); QApplication.processEvents()
        try:
            release=UpdateService().latest()
            if not release:
                self.update_status.setText("Er is nog geen GitHub Release gepubliceerd."); return
            if not release.is_newer:
                self.update_status.setText(f"Versie {__version__} is actueel. Nieuwste release: {release.version}."); return
            if not release.asset_url:
                self.update_status.setText(f"Release {release.version} heeft nog geen Windows-pakket."); return
            answer=QMessageBox.question(self,"NOWA CRM bijwerken",f"Versie {release.version} is beschikbaar. Nu downloaden en installeren?\n\nKlantgegevens blijven lokaal behouden.")
            if answer!=QMessageBox.Yes:return
            self.update_status.setText(f"Versie {release.version} wordt gedownload…"); QApplication.processEvents()
            package=UpdateService().download(release); UpdateService().install_after_exit(package)
            QMessageBox.information(self,"Update gereed","NOWA CRM sluit nu af en start automatisch opnieuw met de nieuwe versie."); QApplication.quit()
        except Exception as exc:
            self.update_status.setText(f"Updatecontrole mislukt: {exc}")
    def refresh_all(self):
        self.refresh_customers(); self.refresh_proposals(); self.refresh_vault(); self.kpis[0].setText(str(self.customers.count())); self.kpis[1].setText(str(self.proposals.count_open())); self.kpis[2].setText(str(self.vault.count()))
    def refresh_customers(self,*_):
        if not hasattr(self,"customer_table"):return
        rows=self.customers.search(self.customer_search.text()); self.customer_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            for c,v in enumerate((x.customer_number,x.name,x.email,x.phone,x.city,str(x.id))):self.customer_table.setItem(r,c,QTableWidgetItem(v))
    def refresh_proposals(self,*_):
        if not hasattr(self,"proposal_table"):return
        rows=self.proposals.list(self.proposal_search.text()); self.proposal_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=(x.number,x.customer_name,x.title,x.status,str(x.revision),f"€ {x.total_cents/100:,.2f}",str(x.id))
            for c,v in enumerate(vals):self.proposal_table.setItem(r,c,QTableWidgetItem(v))
    def refresh_vault(self,*_):
        if not hasattr(self,"vault_table"):return
        rows=self.vault.search_all(self.vault_search.text()); self.vault_table.setRowCount(len(rows))
        for r,x in enumerate(rows):
            vals=(x["customer_name"],x["customer_number"],x["category"],x["label"],x["username"],x["url"],str(x["id"]))
            for c,v in enumerate(vals):self.vault_table.setItem(r,c,QTableWidgetItem(v or ""))
