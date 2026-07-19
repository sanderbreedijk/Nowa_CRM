from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.mail.service import MailService
from nowa_crm.modules.workspace.service import WorkspaceService


class MailPage(QWidget):
    def __init__(self, customers: CustomerService, mail: MailService, workspace: WorkspaceService, parent=None):
        super().__init__(parent); self.customers=customers; self.mail=mail; self.workspace=workspace; self.message_id=None
        root=QVBoxLayout(self); title=QLabel("Mail"); title.setObjectName("Title"); root.addWidget(title)
        sub=QLabel("Lokale klantmail, concepten, sjablonen en historie. Exporteer naar EML om veilig in Outlook te openen."); sub.setObjectName("Subtitle"); root.addWidget(sub)
        filterrow=QHBoxLayout(); self.search=QLineEdit(); self.search.setPlaceholderText("Zoek in onderwerp, afzender, ontvanger of inhoud…"); self.search.textChanged.connect(self.refresh_history)
        self.filter_customer=QComboBox(); self.filter_customer.currentIndexChanged.connect(self.refresh_history);self.dossier_status=QLabel();filterrow.addWidget(self.search,1);filterrow.addWidget(self.filter_customer);filterrow.addWidget(self.dossier_status); root.addLayout(filterrow)
        split=QSplitter(); history=QWidget(); hl=QVBoxLayout(history); self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(["Datum","Klant","Richting","Status","Onderwerp","Adres","ID"]); self.table.setColumnHidden(6,True); self.table.horizontalHeader().setStretchLastSection(True); self.table.doubleClicked.connect(self.load_selected); hl.addWidget(self.table)
        incomingbar=QHBoxLayout();incoming=QPushButton("Ontvangen mail registreren"); incoming.clicked.connect(self.record_incoming);link=QPushButton("Geselecteerde mail aan klant koppelen");link.clicked.connect(self.link_selected);incomingbar.addWidget(incoming);incomingbar.addWidget(link);hl.addLayout(incomingbar)
        editor=QWidget(); form=QFormLayout(editor); self.customer=QComboBox(); self.customer.currentIndexChanged.connect(self.reload_contacts); self.contact=QComboBox()
        self.template=QComboBox(); self.template.currentIndexChanged.connect(self.apply_template); self.to=QLineEdit(); self.cc=QLineEdit(); self.subject=QLineEdit(); self.body=QTextEdit()
        form.addRow("Klant",self.customer); form.addRow("Contact",self.contact); form.addRow("Sjabloon",self.template); form.addRow("Aan",self.to); form.addRow("CC",self.cc); form.addRow("Onderwerp",self.subject); form.addRow("Bericht",self.body)
        buttons=QHBoxLayout()
        for text,handler in (("Nieuw",self.clear),("Concept opslaan",self.save),("Bijlage toevoegen",self.attach),("Openen in Outlook",self.export_eml),("Markeer verzonden",self.mark_sent)):
            button=QPushButton(text); button.clicked.connect(handler); buttons.addWidget(button)
        form.addRow("",buttons); split.addWidget(history); split.addWidget(editor); split.setSizes([620,650]); root.addWidget(split,1); self.reload()

    def reload(self):
        self.customer.blockSignals(True); self.filter_customer.blockSignals(True); self.customer.clear(); self.filter_customer.clear(); self.filter_customer.addItem("Alle klanten",None)
        for customer in self.customers.search():
            label=f"{customer.customer_number} — {customer.name}"; self.customer.addItem(label,customer.id); self.filter_customer.addItem(label,customer.id)
        self.customer.blockSignals(False); self.filter_customer.blockSignals(False)
        self.template.blockSignals(True); self.template.clear(); self.template.addItem("Kies mailsjabloon…",None)
        for item in self.mail.templates():self.template.addItem(f"{item['category']} — {item['name']}",item["id"])
        self.template.blockSignals(False); self.reload_contacts(); self.refresh_history()

    def reload_contacts(self,*_):
        customer_id=self.customer.currentData(); self.contact.clear(); self.contact.addItem("Algemeen klantadres",None)
        if customer_id is None:return
        customer=self.customers.get(customer_id)
        if customer:self.to.setText(customer.email)
        for contact in self.customers.contacts(customer_id):self.contact.addItem(f"{contact.name} — {contact.email}",contact.id)

    def apply_template(self,*_):
        template_id=self.template.currentData(); customer_id=self.customer.currentData()
        if template_id is None or customer_id is None:return
        try:
            progress=self.workspace.progress_mail(customer_id).split("\n\n",2)[-1]
            rendered=self.mail.render_template(template_id,customer_id,self.contact.currentData(),progress=progress)
            self.to.setText(rendered["recipient"]); self.subject.setText(rendered["subject"]); self.body.setPlainText(rendered["body"])
        except Exception as exc:QMessageBox.warning(self,"Mailsjabloon",str(exc))

    def save(self):
        customer_id=self.customer.currentData()
        if customer_id is None:return
        try:
            if self.message_id:self.mail.update_draft(self.message_id,self.to.text(),self.cc.text(),self.subject.text(),self.body.toPlainText())
            else:self.message_id=self.mail.create_draft(customer_id,self.to.text(),self.subject.text(),self.body.toPlainText(),self.contact.currentData(),self.cc.text())
            self.refresh_history(); QMessageBox.information(self,"Mailconcept","Concept lokaal opgeslagen.")
        except Exception as exc:QMessageBox.warning(self,"Mailconcept",str(exc))

    def attach(self):
        if not self.message_id:self.save()
        if not self.message_id:return
        filenames,_=QFileDialog.getOpenFileNames(self,"Bijlagen selecteren")
        try:
            for filename in filenames:self.mail.add_attachment(self.message_id,Path(filename))
            if filenames:QMessageBox.information(self,"Bijlagen",f"{len(filenames)} bijlage(n) lokaal opgeslagen.")
        except Exception as exc:QMessageBox.warning(self,"Bijlagen",str(exc))

    def export_eml(self):
        if not self.message_id:self.save()
        if not self.message_id:return
        try:
            self.mail.update_draft(self.message_id,self.to.text(),self.cc.text(),self.subject.text(),self.body.toPlainText())
            path=self.mail.export_eml(self.message_id); QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))); self.refresh_history()
        except Exception as exc:QMessageBox.warning(self,"EML export",str(exc))

    def mark_sent(self):
        if not self.message_id:return
        self.mail.mark_sent(self.message_id); self.refresh_history()

    def clear(self):
        self.message_id=None; self.to.clear(); self.cc.clear(); self.subject.clear(); self.body.clear(); self.template.setCurrentIndex(0); self.reload_contacts()

    def refresh_history(self,*_):
        rows=self.mail.list_messages(self.filter_customer.currentData(),self.search.text()); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            address=row["sender"] if row["direction"]=="inkomend" else row["recipients"]
            for c,value in enumerate((row["occurred_at"],row["customer_name"],row["direction"],row["status"],row["subject"],address,row["id"])):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))
        stats=self.mail.dossier_stats();self.dossier_status.setText(f"{stats['linked']} gekoppeld · {stats['unlinked']} te koppelen")

    def link_selected(self):
        row=self.table.currentRow();item=self.table.item(row,6) if row>=0 else None
        if not item:return
        customers=self.customers.search();labels=[f"{x.customer_number} — {x.name}" for x in customers]
        if not labels:return
        label,ok=QInputDialog.getItem(self,"Mail aan klant koppelen","Klant",labels,0,False)
        if ok:self.mail.link_customer(int(item.text()),customers[labels.index(label)].id);self.refresh_history()

    def load_selected(self,*_):
        row=self.table.currentRow(); item=self.table.item(row,6) if row>=0 else None
        if not item:return
        message=self.mail.get(int(item.text()))
        if not message:return
        self.message_id=message["id"]; index=self.customer.findData(message["customer_id"])
        if index>=0:self.customer.setCurrentIndex(index)
        self.to.setText(message["recipients"]); self.cc.setText(message["cc"]); self.subject.setText(message["subject"]); self.body.setPlainText(message["body"])

    def open_message(self,message_id: int):
        message=self.mail.get(message_id)
        if not message:return
        self.message_id=message_id; index=self.customer.findData(message["customer_id"])
        if index>=0:self.customer.setCurrentIndex(index)
        self.to.setText(message["recipients"]); self.cc.setText(message["cc"])
        self.subject.setText(message["subject"]); self.body.setPlainText(message["body"]); self.refresh_history()

    def record_incoming(self):
        sender,ok=QInputDialog.getText(self,"Ontvangen mail","Afzender")
        if not ok:return
        subject,ok=QInputDialog.getText(self,"Ontvangen mail","Onderwerp")
        if not ok:return
        body,ok=QInputDialog.getMultiLineText(self,"Ontvangen mail","Inhoud")
        if ok:
            self.mail.record_incoming(sender,"NOWA Solutions",subject,body); self.refresh_history()
