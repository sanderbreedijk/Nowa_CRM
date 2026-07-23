from __future__ import annotations

from PySide6.QtWidgets import (QComboBox,QFormLayout,QFrame,QGridLayout,QHBoxLayout,QInputDialog,QLabel,
                               QLineEdit,QMessageBox,QPushButton,QSplitter,QTableWidget,QTableWidgetItem,
                               QVBoxLayout,QWidget)

from nowa_crm.modules.customers.service import CustomerService
from nowa_crm.modules.servicedesk.service import ServiceDeskService


class ServiceDeskPage(QWidget):
    def __init__(self,customers: CustomerService,service: ServiceDeskService,open_mail=None,open_call=None,open_vault=None,parent=None):
        super().__init__(parent);self.customers=customers;self.service=service;self.ticket_id=None
        self.open_mail,self.open_call,self.open_vault=open_mail,open_call,open_vault
        root=QVBoxLayout(self);title=QLabel("Slimme servicedesk");title.setObjectName("Title");root.addWidget(title)
        sub=QLabel("Bewaak servicevragen, automatische SLA-deadlines, voortgang en bestede tijd.");sub.setObjectName("Subtitle");root.addWidget(sub)
        filters=QHBoxLayout();self.search=QLineEdit();self.search.setPlaceholderText("Zoek ticket, klant of onderwerp…");self.search.textChanged.connect(self.reload)
        self.customer_filter=QComboBox();self.customer_filter.currentIndexChanged.connect(self.reload)
        self.status_filter=QComboBox();self.status_filter.addItem("Alle statussen","");self.status_filter.addItems(ServiceDeskService.STATUSES);self.status_filter.currentIndexChanged.connect(self.reload)
        self.priority_filter=QComboBox();self.priority_filter.addItem("Alle prioriteiten","");self.priority_filter.addItems(ServiceDeskService.PRIORITIES);self.priority_filter.currentIndexChanged.connect(self.reload)
        self.sla_filter=QComboBox();self.sla_filter.addItem("Alle SLA-statussen","");self.sla_filter.addItems(["Overschreden","Dreigt","Binnen SLA","Geen SLA","Afgerond"]);self.sla_filter.currentIndexChanged.connect(self.reload)
        for widget in (self.search,self.customer_filter,self.status_filter,self.priority_filter,self.sla_filter):filters.addWidget(widget,1 if widget is self.search else 0)
        root.addLayout(filters)
        grid=QGridLayout();self.kpis=[]
        for col,name in enumerate(("Open","Kritiek","SLA overschreden","SLA dreigt","Afgerond","Bestede uren")):
            card=QFrame();card.setObjectName("Card");box=QVBoxLayout(card);value=QLabel("0");value.setObjectName("Kpi");box.addWidget(value);box.addWidget(QLabel(name));grid.addWidget(card,0,col);self.kpis.append(value)
        root.addLayout(grid)
        split=QSplitter();left=QWidget();ll=QVBoxLayout(left);self.table=QTableWidget(0,10)
        self.table.setHorizontalHeaderLabels(["Nummer","Klant","Onderwerp","Prioriteit","Status","Eigenaar","SLA-deadline","SLA-status","Tijd","ID"]);self.table.setColumnHidden(9,True);self.table.horizontalHeader().setStretchLastSection(True);self.table.doubleClicked.connect(self.load_selected);ll.addWidget(self.table)
        buttons=QHBoxLayout();create=QPushButton("Nieuw ticket");create.setObjectName("Primary");create.clicked.connect(self.create_ticket);maintenance=QPushButton("Onderhoudstaak");maintenance.clicked.connect(self.add_maintenance);buttons.addWidget(create);buttons.addWidget(maintenance);buttons.addStretch();ll.addLayout(buttons)
        right=QWidget();form=QFormLayout(right);self.heading=QLabel("Selecteer een ticket");self.heading.setWordWrap(True);form.addRow(self.heading)
        self.updates=QTableWidget(0,3);self.updates.setHorizontalHeaderLabels(["Datum","Status","Voortgang"]);self.updates.horizontalHeader().setStretchLastSection(True);form.addRow(self.updates)
        row=QHBoxLayout()
        for text,handler in (("Voortgang toevoegen",self.add_update),("Tijd registreren",self.add_time),("Ticket sluiten",self.close_ticket)):
            button=QPushButton(text);button.clicked.connect(handler);row.addWidget(button)
        form.addRow(row);split.addWidget(left);split.addWidget(right);split.setSizes([930,470]);root.addWidget(split,1);self.reload_customers()
        direct=QHBoxLayout()
        for text,handler in (("Klant mailen",self.mail_customer),("Open telefonie",self.call_customer),("Open IT-kluis",self.vault_customer)):
            button=QPushButton(text);button.clicked.connect(handler);direct.addWidget(button)
        form.addRow(direct)

    def reload_customers(self):
        current=self.customer_filter.currentData();self.customer_filter.blockSignals(True);self.customer_filter.clear();self.customer_filter.addItem("Alle klanten",None)
        for customer in self.customers.search():self.customer_filter.addItem(f"{customer.customer_number} — {customer.name}",customer.id)
        if current is not None:
            index=self.customer_filter.findData(current)
            if index>=0:self.customer_filter.setCurrentIndex(index)
        self.customer_filter.blockSignals(False);self.reload()

    def reload(self,*_):
        customer_id=self.customer_filter.currentData();rows=self.service.list(customer_id,self.status_filter.currentData() or "",self.search.text(),self.priority_filter.currentData() or "",sla=self.sla_filter.currentData() or "");self.table.setRowCount(len(rows))
        for r,row in enumerate(rows):
            values=(row["number"],row["customer_name"],row["subject"],row["priority"],row["status"],row["owner"],row["sla_due_at"],row["sla_state"],f"{row['minutes']/60:.2f} uur",row["id"])
            for c,value in enumerate(values):self.table.setItem(r,c,QTableWidgetItem(str(value or "")))
        stats=self.service.stats(customer_id)
        for label,value in zip(self.kpis,(stats["open"],stats["critical"],stats["overdue"],stats["due_soon"],stats["closed"],f"{stats['minutes']/60:.1f}")):label.setText(str(value))

    def create_ticket(self):
        customers=self.customers.search()
        if not customers:QMessageBox.information(self,"Servicedesk","Voeg eerst een klant toe.");return
        labels=[f"{x.customer_number} — {x.name}" for x in customers];label,ok=QInputDialog.getItem(self,"Nieuw ticket","Klant",labels,0,False)
        if not ok:return
        subject,ok=QInputDialog.getText(self,"Nieuw ticket","Onderwerp")
        if not ok:return
        description,ok=QInputDialog.getMultiLineText(self,"Nieuw ticket","Omschrijving")
        if not ok:return
        priority,ok=QInputDialog.getItem(self,"Nieuw ticket","Prioriteit",list(ServiceDeskService.PRIORITIES),1,False)
        if not ok:return
        owner,ok=QInputDialog.getText(self,"Nieuw ticket","Behandelaar",text="NOWA")
        if not ok:return
        sla,ok=QInputDialog.getText(self,"Nieuw ticket","SLA-deadline (leeg = automatisch)")
        if ok:self.ticket_id=self.service.create(customers[labels.index(label)].id,subject,description,priority=priority,owner=owner,sla_due_at=sla);self.reload();self.load_ticket()

    def create_ticket_for_customer(self,customer_id):
        customer=self.customers.get(customer_id)
        if not customer:return
        subject,ok=QInputDialog.getText(self,"Nieuw serviceticket",f"Onderwerp voor {customer.name}")
        if not ok or not subject.strip():return
        description,ok=QInputDialog.getMultiLineText(self,"Nieuw serviceticket","Omschrijving")
        if not ok:return
        priority,ok=QInputDialog.getItem(self,"Nieuw serviceticket","Prioriteit",list(ServiceDeskService.PRIORITIES),1,False)
        if not ok:return
        self.ticket_id=self.service.create(customer_id,subject,description,priority=priority,owner="NOWA")
        self.reload();self.load_ticket()

    def load_selected(self,*_):
        row=self.table.currentRow();item=self.table.item(row,9) if row>=0 else None
        if item:self.ticket_id=int(item.text());self.load_ticket()

    def open_ticket(self,ticket_id):self.ticket_id=ticket_id;self.reload();self.load_ticket()

    def load_ticket(self):
        ticket=self.service.get(self.ticket_id) if self.ticket_id else None
        if not ticket:return
        self.heading.setText(f"{ticket['number']} · {ticket['subject']}\n{ticket['customer_name']} · {ticket['priority']} · {ticket['status']}\nSLA: {ticket['sla_due_at']} · {ticket['sla_state']}\n{ticket['description']}")
        rows=self.service.updates(self.ticket_id);self.updates.setRowCount(len(rows))
        for r,row in enumerate(rows):
            for c,value in enumerate((row["created_at"],row["status"],row["body"])):self.updates.setItem(r,c,QTableWidgetItem(str(value or "")))

    def add_update(self):
        if not self.ticket_id:return
        body,ok=QInputDialog.getMultiLineText(self,"Ticketvoortgang","Voortgang")
        if not ok:return
        status,ok=QInputDialog.getItem(self,"Ticketvoortgang","Nieuwe status",["",*ServiceDeskService.STATUSES],0,False)
        if ok:self.service.add_update(self.ticket_id,body,status);self.reload();self.load_ticket()

    def add_time(self):
        if not self.ticket_id:return
        minutes,ok=QInputDialog.getInt(self,"Tijd registreren","Minuten",15,1,1440,5)
        if not ok:return
        description,ok=QInputDialog.getText(self,"Tijd registreren","Werkzaamheden")
        if ok:self.service.add_time(self.ticket_id,minutes,description);self.reload();self.load_ticket()

    def close_ticket(self):
        if not self.ticket_id:return
        resolution,ok=QInputDialog.getMultiLineText(self,"Ticket sluiten","Oplossing")
        if ok:self.service.close(self.ticket_id,resolution);self.reload();self.load_ticket()

    def add_maintenance(self):
        customers=self.customers.search()
        if not customers:return
        labels=[f"{x.customer_number} — {x.name}" for x in customers];label,ok=QInputDialog.getItem(self,"Onderhoudstaak","Klant",labels,0,False)
        if not ok:return
        title,ok=QInputDialog.getText(self,"Onderhoudstaak","Taak")
        if not ok:return
        frequency,ok=QInputDialog.getItem(self,"Onderhoudstaak","Herhaling",["Wekelijks","Maandelijks","Per kwartaal","Jaarlijks"],1,False)
        if not ok:return
        due,ok=QInputDialog.getText(self,"Onderhoudstaak","Eerstvolgende datum (jjjj-mm-dd)")
        if ok:self.service.add_maintenance(customers[labels.index(label)].id,title,frequency,due);QMessageBox.information(self,"Onderhoudstaak","Terugkerende onderhoudstaak lokaal opgeslagen.")

    def mail_customer(self):
        ticket=self.service.get(self.ticket_id) if self.ticket_id else None
        if ticket and self.open_mail:self.open_mail(ticket["customer_id"])

    def call_customer(self):
        if self.ticket_id and self.open_call:self.open_call(None)

    def vault_customer(self):
        ticket=self.service.get(self.ticket_id) if self.ticket_id else None
        if ticket and self.open_vault:self.open_vault(ticket["customer_phone"])
