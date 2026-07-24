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
        self.filter_customer=QComboBox(); self.filter_customer.currentIndexChanged.connect(self.refresh_history)
        self.queue=QComboBox()
        for label,value in (("Alle mail","alle"),("Te behandelen","open"),("Ongekoppeld","ongekoppeld"),("Concepten","concepten"),("Afgerond","afgerond")):self.queue.addItem(label,value)
        self.queue.currentIndexChanged.connect(self.refresh_history);self.dossier_status=QLabel();filterrow.addWidget(self.search,1);filterrow.addWidget(self.queue);filterrow.addWidget(self.filter_customer);filterrow.addWidget(self.dossier_status); root.addLayout(filterrow)
        split=QSplitter(); history=QWidget(); hl=QVBoxLayout(history); self.table=QTableWidget(0,10); self.table.setHorizontalHeaderLabels(["Datum","Klant","Prioriteit","Behandeling","Onderwerp","Adres","Opvolgen","Toegewezen","Richting","ID"]); self.table.setColumnHidden(9,True); self.table.horizontalHeader().setStretchLastSection(True); self.table.doubleClicked.connect(self.load_selected); hl.addWidget(self.table)
        incomingbar=QHBoxLayout()
        for text,handler in (("Ontvangen mail registreren",self.record_incoming),("Aan klant koppelen",self.link_selected),("Beantwoorden",self.reply_selected),("Behandeling instellen",self.triage_selected),("Actiepunt maken",self.create_followup),("Afronden",self.complete_selected)):
            button=QPushButton(text);button.clicked.connect(handler);incomingbar.addWidget(button)
        hl.addLayout(incomingbar)
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
        rows=self.mail.list_messages(self.filter_customer.currentData(),self.search.text(),self.queue.currentData() or "alle"); self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            address=row["sender"] if row["direction"]=="inkomend" else row["recipients"]
            treatment={"open":"Open","wacht_op_klant":"Wacht op klant","afgerond":"Afgerond"}.get(row["triage_state"],row["triage_state"])
            for c,value in enumerate((row["occurred_at"],row["customer_name"],row["priority"],treatment,row["subject"],address,row["follow_up_at"],row["assigned_to"],row["direction"],row["id"])):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))
        stats=self.mail.queue_stats();self.dossier_status.setText(f"{stats['open']} open · {stats['urgent']} urgent · {stats['unlinked']} te koppelen")

    def selected_message_id(self):
        row=self.table.currentRow();item=self.table.item(row,9) if row>=0 else None
        return int(item.text()) if item else None

    def link_selected(self):
        message_id=self.selected_message_id()
        if not message_id:return
        customers=self.customers.search();labels=[f"{x.customer_number} — {x.name}" for x in customers]
        if not labels:return
        label,ok=QInputDialog.getItem(self,"Mail aan klant koppelen","Klant",labels,0,False)
        if ok:self.mail.link_customer(message_id,customers[labels.index(label)].id);self.refresh_history()

    def load_selected(self,*_):
        message_id=self.selected_message_id()
        if not message_id:return
        message=self.mail.get(message_id)
        if not message:return
        self.message_id=message["id"]; index=self.customer.findData(message["customer_id"])
        if index>=0:self.customer.setCurrentIndex(index)
        self.to.setText(message["recipients"]); self.cc.setText(message["cc"]); self.subject.setText(message["subject"]); self.body.setPlainText(message["body"])

    def reply_selected(self):
        message_id=self.selected_message_id()
        if not message_id:return
        try:self.open_message(self.mail.reply_draft(message_id))
        except Exception as exc:QMessageBox.warning(self,"Mail beantwoorden",str(exc))

    def triage_selected(self):
        message_id=self.selected_message_id()
        if not message_id:return
        message=self.mail.get(message_id);states=["Open","Wacht op klant","Afgerond"]
        state,ok=QInputDialog.getItem(self,"Behandeling","Status",states,0,False)
        if not ok:return
        priorities=list(self.mail.PRIORITIES);priority,ok=QInputDialog.getItem(self,"Behandeling","Prioriteit",priorities,priorities.index(message["priority"]),False)
        if not ok:return
        owner,ok=QInputDialog.getText(self,"Behandeling","Toegewezen aan",text=message["assigned_to"] or self.mail.actor)
        if not ok:return
        followup,ok=QInputDialog.getText(self,"Behandeling","Opvolgen op (optioneel: jjjj-mm-dd)",text=message["follow_up_at"])
        if not ok:return
        values={"Open":"open","Wacht op klant":"wacht_op_klant","Afgerond":"afgerond"}
        try:self.mail.triage(message_id,values[state],priority,owner,followup);self.refresh_history()
        except Exception as exc:QMessageBox.warning(self,"Behandeling",str(exc))

    def create_followup(self):
        message_id=self.selected_message_id()
        if not message_id:return
        message=self.mail.get(message_id)
        if not message or message["customer_id"] is None:
            QMessageBox.information(self,"Actiepunt","Koppel de mail eerst aan een klant.");return
        title,ok=QInputDialog.getText(self,"Actiepunt maken","Titel",text=f"Mail opvolgen: {message['subject']}")
        if not ok:return
        due,ok=QInputDialog.getText(self,"Actiepunt maken","Deadline (jjjj-mm-dd)",text=message["follow_up_at"][:10])
        if not ok:return
        duration,ok=QInputDialog.getInt(self,"Benodigde tijd","Hoeveel minuten zijn nodig?",60,5,1440,5)
        if not ok:return
        try:
            self.workspace.add_action(message["customer_id"],title,self.mail.actor,due,message["priority"],message["body"][:500],
                "E-mail opvolgen",source_type="E-mail",source_id=message_id,duration_minutes=duration)
            self.mail.triage(message_id,"open",message["priority"],self.mail.actor,due);self.refresh_history()
            QMessageBox.information(self,"Actiepunt","Het actiepunt staat in de werkvoorraad en het klantdossier.")
        except Exception as exc:QMessageBox.warning(self,"Actiepunt",str(exc))

    def complete_selected(self):
        message_id=self.selected_message_id()
        if not message_id:return
        message=self.mail.get(message_id)
        self.mail.triage(message_id,"afgerond",message["priority"],message["assigned_to"],message["follow_up_at"]);self.refresh_history()

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
