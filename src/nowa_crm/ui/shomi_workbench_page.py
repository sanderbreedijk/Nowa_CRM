from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView,QComboBox,QFrame,QGridLayout,QHBoxLayout,QHeaderView,
                               QLabel,QLineEdit,QMessageBox,QPushButton,QSpinBox,QTableWidget,
                               QTableWidgetItem,QTextEdit,QVBoxLayout,QWidget)


class ShomiWorkbenchPage(QWidget):
    def __init__(self, service, customers, open_call, parent=None):
        super().__init__(parent);self.service=service;self.customers=customers;self.open_call=open_call
        self.current_id=None;self.rows=[];self.current={}
        root=QVBoxLayout(self);root.setContentsMargins(28,24,28,24);root.setSpacing(14)
        head=QHBoxLayout();title=QLabel("Shomi-werkbak");title.setObjectName("Title");head.addWidget(title);head.addStretch()
        self.status=QComboBox();self.status.addItems(["Te beoordelen","Concept","Behandeld","Gearchiveerd","Alle"])
        self.status.currentTextChanged.connect(self.reload);refresh=QPushButton("Vernieuwen");refresh.clicked.connect(self.reload)
        head.addWidget(QLabel("Toon"));head.addWidget(self.status);head.addWidget(refresh);root.addLayout(head)
        sub=QLabel("Controleer klant, contact, samenvatting en vervolgacties. Taken en agenda-items worden pas na jouw akkoord aangemaakt.")
        sub.setObjectName("Subtitle");sub.setWordWrap(True);root.addWidget(sub)
        body=QGridLayout();body.setColumnStretch(0,4);body.setColumnStretch(1,7);body.setHorizontalSpacing(14);root.addLayout(body,1)

        queue_card=QFrame();queue_card.setObjectName("Card");queue_box=QVBoxLayout(queue_card)
        queue_head=QHBoxLayout();queue_title=QLabel("Binnengekomen gesprekken");queue_title.setObjectName("SectionTitle")
        self.count=QLabel("0");queue_head.addWidget(queue_title);queue_head.addStretch();queue_head.addWidget(self.count);queue_box.addLayout(queue_head)
        self.search=QLineEdit();self.search.setPlaceholderText("Zoek klant, onderwerp of telefoonnummer…");self.search.textChanged.connect(self._filter);queue_box.addWidget(self.search)
        self.queue=QTableWidget(0,4);self.queue.setHorizontalHeaderLabels(["Ontvangen","Klant","Onderwerp","ID"]);self.queue.setColumnHidden(3,True)
        self.queue.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);self.queue.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers);self.queue.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.queue.itemSelectionChanged.connect(self._load_selected);queue_box.addWidget(self.queue,1);body.addWidget(queue_card,0,0)

        detail=QFrame();detail.setObjectName("Card");box=QVBoxLayout(detail);box.setSpacing(10)
        self.detail_title=QLabel("Selecteer een gesprek");self.detail_title.setObjectName("SectionTitle");self.detail_title.setWordWrap(True);box.addWidget(self.detail_title)
        links=QHBoxLayout();self.customer=QComboBox();self.customer.currentIndexChanged.connect(self._load_contacts);self.contact=QComboBox()
        links.addWidget(QLabel("Klant"));links.addWidget(self.customer,2);links.addWidget(QLabel("Contact"));links.addWidget(self.contact,2);box.addLayout(links)
        self.meta=QLabel();self.meta.setObjectName("Subtitle");box.addWidget(self.meta)
        box.addWidget(QLabel("Gesprekssamenvatting"));self.summary=QTextEdit();self.summary.setMaximumHeight(145);box.addWidget(self.summary)
        actions_head=QHBoxLayout();actions_title=QLabel("Vervolgacties");actions_title.setObjectName("SectionTitle");actions_head.addWidget(actions_title);actions_head.addStretch()
        add=QPushButton("+ Actie");add.clicked.connect(self._add_action);remove=QPushButton("Verwijder");remove.clicked.connect(self._remove_action)
        actions_head.addWidget(add);actions_head.addWidget(remove);box.addLayout(actions_head)
        self.actions=QTableWidget(0,6);self.actions.setHorizontalHeaderLabels(["Plannen","Actie","Datum / tijd","Min.","Prioriteit","Toelichting"])
        self.actions.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch);self.actions.horizontalHeader().setSectionResizeMode(5,QHeaderView.ResizeMode.Stretch)
        self.actions.verticalHeader().setDefaultSectionSize(36);box.addWidget(self.actions,1)
        self.notes=QLineEdit();self.notes.setPlaceholderText("Interne beoordelingsnotitie (blijft lokaal)");box.addWidget(self.notes)
        buttons=QHBoxLayout();open_button=QPushButton("Open gesprek");open_button.clicked.connect(self._open_call)
        archive=QPushButton("Archiveren");archive.clicked.connect(self._archive);draft=QPushButton("Concept opslaan");draft.clicked.connect(lambda:self._save(False))
        complete=QPushButton("Behandelen en plannen");complete.setObjectName("Primary");complete.clicked.connect(lambda:self._save(True))
        buttons.addWidget(open_button);buttons.addWidget(archive);buttons.addStretch();buttons.addWidget(draft);buttons.addWidget(complete);box.addLayout(buttons);body.addWidget(detail,0,1)
        self.reload()

    def reload(self,*_):
        selected=self.current_id;self.rows=self.service.shomi_reviews(self.status.currentText());self._filter()
        if selected:
            for row in range(self.queue.rowCount()):
                if int(self.queue.item(row,3).text())==selected:self.queue.selectRow(row);break

    def _filter(self,*_):
        term=self.search.text().strip().lower()
        shown=[row for row in self.rows if not term or term in " ".join(str(row.get(k,"")) for k in ("customer_name","subject","phone_number","summary")).lower()]
        self.queue.setRowCount(len(shown));self.count.setText(str(len(shown)))
        for r,row in enumerate(shown):
            for c,value in enumerate((row["received_at"][:16],row["customer_name"],row["subject"],row["id"])):
                self.queue.setItem(r,c,QTableWidgetItem(str(value or "")))
        if shown and self.current_id is None:self.queue.selectRow(0)

    def _load_selected(self):
        row=self.queue.currentRow()
        if row<0:return
        item=next((x for x in self.rows if x["id"]==int(self.queue.item(row,3).text())),None)
        if not item:return
        self.current_id=item["id"];self.current=item;self.detail_title.setText(item["subject"])
        self.meta.setText(f"{item['received_at'][:16]}  ·  {item['direction']}  ·  {item['phone_number']}  ·  {item['review_status']}")
        self.customer.blockSignals(True);self.customer.clear();self.customer.addItem("Nog niet gekoppeld",None)
        for customer in self.customers.search():self.customer.addItem(f"{customer.customer_number} · {customer.name}",customer.id)
        index=self.customer.findData(item["customer_id"]);self.customer.setCurrentIndex(max(0,index));self.customer.blockSignals(False)
        self._load_contacts();index=self.contact.findData(item.get("contact_id"));self.contact.setCurrentIndex(max(0,index))
        self.summary.setPlainText(item["summary"]);self.notes.setText(item.get("reviewer_notes",""));self.actions.setRowCount(0)
        try:points=json.loads(item["action_points_json"] or "[]")
        except (TypeError,json.JSONDecodeError):points=[]
        for point in points:self._add_action(point)

    def _load_contacts(self,*_):
        selected=self.contact.currentData() if self.contact.count() else None;self.contact.clear();self.contact.addItem("Geen contactpersoon",None)
        if self.customer.currentData():
            for contact in self.customers.contacts(self.customer.currentData()):self.contact.addItem(f"{contact.name} · {contact.role}",contact.id)
        self.contact.setCurrentIndex(max(0,self.contact.findData(selected)))

    def _add_action(self,point=None):
        point=point or {};row=self.actions.rowCount();self.actions.insertRow(row)
        select=QTableWidgetItem();select.setFlags(select.flags()|Qt.ItemFlag.ItemIsUserCheckable)
        select.setCheckState(Qt.CheckState.Checked if point.get("selected",True) else Qt.CheckState.Unchecked);self.actions.setItem(row,0,select)
        self.actions.setItem(row,1,QTableWidgetItem(str(point.get("title",""))))
        self.actions.setItem(row,2,QTableWidgetItem(str(point.get("reminder_at") or point.get("due_date",""))))
        duration=QSpinBox();duration.setRange(5,1440);duration.setSingleStep(5);duration.setValue(int(point.get("duration_minutes",60) or 60));self.actions.setCellWidget(row,3,duration)
        priority=QComboBox();priority.addItems(["Laag","Normaal","Hoog"]);priority.setCurrentText(str(point.get("priority","Normaal")).title());self.actions.setCellWidget(row,4,priority)
        self.actions.setItem(row,5,QTableWidgetItem(str(point.get("detail",""))))

    def _remove_action(self):
        if self.actions.currentRow()>=0:self.actions.removeRow(self.actions.currentRow())

    def _points(self):
        result=[]
        for row in range(self.actions.rowCount()):
            moment=(self.actions.item(row,2).text() if self.actions.item(row,2) else "").strip()
            result.append({"selected":self.actions.item(row,0).checkState()==Qt.CheckState.Checked,
                "title":self.actions.item(row,1).text() if self.actions.item(row,1) else "",
                "due_date":moment[:10] if moment else "","reminder_at":moment if "T" in moment or " " in moment else "",
                "duration_minutes":self.actions.cellWidget(row,3).value(),"priority":self.actions.cellWidget(row,4).currentText(),
                "detail":self.actions.item(row,5).text() if self.actions.item(row,5) else ""})
        return result

    def _save(self,complete):
        if not self.current_id:return
        if complete and not self.customer.currentData():QMessageBox.warning(self,"Shomi-werkbak","Kies eerst de juiste klant.");return
        try:
            result=self.service.save_shomi_review(self.current_id,self.customer.currentData(),self.contact.currentData(),
                self.summary.toPlainText(),self._points(),self.notes.text(),complete)
            if complete:
                QMessageBox.information(self,"Shomi verwerkt",f"{result['actions_created']} acties aangemaakt, waarvan {result['appointments_created']} met een tijdstip.")
                self.current_id=None
            self.reload()
        except Exception as exc:QMessageBox.warning(self,"Shomi-werkbak",str(exc))

    def _archive(self):
        if not self.current_id or QMessageBox.question(self,"Shomi archiveren","Dit gesprek zonder nieuwe acties archiveren?")!=QMessageBox.StandardButton.Yes:return
        self.service.archive_shomi_review(self.current_id);self.current_id=None;self.reload()

    def _open_call(self):
        if self.current_id:self.open_call(self.current["call_id"])
