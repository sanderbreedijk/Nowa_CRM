from __future__ import annotations

from PySide6.QtCore import Qt,QUrl,QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDialog,QDialogButtonBox,QDoubleSpinBox,QFormLayout,
    QFileDialog,QGridLayout,QGroupBox,QHeaderView,QHBoxLayout,QInputDialog,QLabel,QLineEdit,QMessageBox,
    QPushButton,QSplitter,QTableWidget,QTableWidgetItem,QTabWidget,QTextEdit,QVBoxLayout,
    QWidget,QAbstractItemView)

from nowa_crm.modules.proposals.pdf import export_proposal_pdf
from nowa_crm.modules.proposals.service import ProposalService
from nowa_crm.modules.proposals.approval import ProposalApprovalService
from nowa_crm.modules.proposals.delivery import ProposalDeliveryService

def money(cents:int)->str:
    return f"EUR {cents/100:,.2f}".replace(",","X").replace(".",",").replace("X",".")

class ProposalDialog(QDialog):
    def __init__(self,service:ProposalService,proposal_id:int,parent=None,mail=None):
        super().__init__(parent);self.service=service;self.proposal_id=proposal_id;self.approvals=ProposalApprovalService(service)
        self.delivery=ProposalDeliveryService(service,mail) if mail else None
        self.setWindowTitle("Professionele offerte-editor")
        self.setWindowFlags(Qt.Window|Qt.WindowMinMaxButtonsHint|Qt.WindowCloseButtonHint)
        self.setMinimumSize(1024,700);self.resize(1500,900)
        self.editing_line_id=None;self._loading_form=False
        self.autosave=QTimer(self);self.autosave.setSingleShot(True);self.autosave.setInterval(900);self.autosave.timeout.connect(self._autosave_selected)
        box=QVBoxLayout(self);box.setContentsMargins(18,16,18,14);box.setSpacing(10)
        top=QHBoxLayout();self.heading=QLabel();self.heading.setObjectName("Title");self.heading.setWordWrap(True);top.addWidget(self.heading,1)
        self.save_state=QLabel("Alle wijzigingen lokaal opgeslagen");self.save_state.setObjectName("SummaryPill");top.addWidget(self.save_state)
        top.addWidget(QLabel("Status"));self.status=QComboBox();self.status.setMinimumWidth(140);self.status.addItems(service.STATUSES);self.status.currentTextChanged.connect(self._status);top.addWidget(self.status)
        self.fullscreen=QPushButton("Volledig scherm");self.fullscreen.clicked.connect(self._toggle_fullscreen);top.addWidget(self.fullscreen);box.addLayout(top)

        summary=QHBoxLayout();self.once_total=QLabel();self.once_total.setObjectName("MiniStatCard");self.month_total=QLabel();self.month_total.setObjectName("MiniStatCard");self.line_count=QLabel();self.line_count.setObjectName("MiniStatCard")
        for card in (self.once_total,self.month_total,self.line_count):card.setAlignment(Qt.AlignCenter);card.setMinimumHeight(54);summary.addWidget(card,1)
        box.addLayout(summary)

        splitter=QSplitter(Qt.Vertical)
        lines=QGroupBox("Offerteregels");lines_box=QVBoxLayout(lines)
        line_head=QHBoxLayout();line_head.addWidget(QLabel("Toon hoofdstuk"));self.group_filter=QComboBox();self.group_filter.addItem("Alle hoofdstukken",None);self.group_filter.currentIndexChanged.connect(self.refresh);line_head.addWidget(self.group_filter);self.group_subtotal=QLabel();self.group_subtotal.setObjectName("SummaryPill");line_head.addWidget(self.group_subtotal);line_head.addStretch();hint=QLabel("Dubbelklik een regel om deze te bewerken");hint.setObjectName("Subtitle");line_head.addWidget(hint);lines_box.addLayout(line_head)
        self.table=QTableWidget(0,10);self.table.setHorizontalHeaderLabels(["Actief","Optie","Groep","Soort","Omschrijving","Aantal","Periode","Prijs","Totaal","ID"]);self.table.setColumnHidden(9,True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.SingleSelection);self.table.setAlternatingRowColors(True);self.table.verticalHeader().setVisible(False)
        header=self.table.horizontalHeader();header.setSectionResizeMode(QHeaderView.ResizeToContents);header.setSectionResizeMode(4,QHeaderView.Stretch);header.setMinimumSectionSize(72)
        self.table.doubleClicked.connect(self._load_selected);lines_box.addWidget(self.table);splitter.addWidget(lines)

        lower=QTabWidget();lower.setDocumentMode(True)
        edit_group=QGroupBox("Regel bewerken");form=QGridLayout(edit_group);form.setHorizontalSpacing(10);form.setVerticalSpacing(8)
        self.group=QLineEdit();self.group.setPlaceholderText("Bijvoorbeeld Migratie, Licenties of Hardware");self.kind=QComboBox();self.kind.addItems(["dienst","uren","licentie","hardware","korting"]);self.description=QLineEdit();self.description.setPlaceholderText("Duidelijke omschrijving voor de klant");self.quantity=QDoubleSpinBox();self.quantity.setRange(.01,99999);self.quantity.setDecimals(2);self.quantity.setValue(1);self.period=QComboBox();self.period.addItems(["eenmalig","maandelijks"]);self.price=QDoubleSpinBox();self.price.setRange(0,9999999);self.price.setDecimals(2);self.price.setPrefix("EUR ")
        form.addWidget(QLabel("Groep"),0,0);form.addWidget(self.group,0,1);form.addWidget(QLabel("Soort"),0,2);form.addWidget(self.kind,0,3)
        form.addWidget(QLabel("Omschrijving"),1,0);form.addWidget(self.description,1,1,1,3)
        form.addWidget(QLabel("Aantal"),2,0);form.addWidget(self.quantity,2,1);form.addWidget(QLabel("Facturatie"),2,2);form.addWidget(self.period,2,3)
        form.addWidget(QLabel("Prijs excl. btw"),3,0);form.addWidget(self.price,3,1);self.optional=QCheckBox("Optionele regel — niet meetellen in offertetotaal");form.addWidget(self.optional,3,2,1,2)
        line_actions=QGridLayout()
        for index,(label,callback) in enumerate((("Nieuwe regel toevoegen",self._add),("Wijzig geselecteerde",self._update),("Dupliceren",self._duplicate_line),("Verwijderen",self._delete),("In-/uitschakelen",self._toggle),("Omhoog",lambda:self._move(-1)),("Omlaag",lambda:self._move(1)))):
            b=QPushButton(label);b.clicked.connect(callback);line_actions.addWidget(b,index//4,index%4)
        form.addLayout(line_actions,4,0,1,4);lower.addTab(edit_group,"Regel bewerken")

        tools=QGroupBox("Offertehulpmiddelen");toolbox=QGridLayout(tools);self.catalog=QComboBox();self._reload_catalog();toolbox.addWidget(QLabel("Productcatalogus"),0,0,1,2);toolbox.addWidget(self.catalog,1,0);b=QPushButton("Toevoegen");b.clicked.connect(self._add_catalog);toolbox.addWidget(b,1,1)
        self.template=QComboBox();self.template.addItem("Kies sjabloon...",None)
        for x in service.templates():self.template.addItem(x["name"],x["id"])
        toolbox.addWidget(QLabel("Offertesjabloon"),2,0,1,2);toolbox.addWidget(self.template,3,0);b=QPushButton("Toepassen");b.clicked.connect(self._apply_template);toolbox.addWidget(b,3,1)
        tool_actions=[("Hoofdstukken",self._sections),("Uit klantdossier",self._assets),("Bereken uit intake",self._calculate),("Revisie bewaren",self._revision),("Revisiegeschiedenis",self._revision_history),("Voorbeeld / PDF",self._pdf),("Online akkoord",self._online_approval)]
        if self.delivery:tool_actions.append(("Verzenden via NOWA-mailbox",self._send_proposal))
        for index,(label,callback) in enumerate(tool_actions):
            b=QPushButton(label);b.clicked.connect(callback);toolbox.addWidget(b,4+index//2,index%2)
        lower.addTab(tools,"Catalogus, sjablonen en revisies");splitter.addWidget(lower);splitter.setStretchFactor(0,3);splitter.setStretchFactor(1,2);splitter.setSizes([500,270]);box.addWidget(splitter,1)

        for field in (self.group,self.description):field.textEdited.connect(self._schedule_autosave)
        for field in (self.kind,self.period):field.currentTextChanged.connect(self._schedule_autosave)
        for field in (self.quantity,self.price):field.valueChanged.connect(self._schedule_autosave)
        self.optional.toggled.connect(self._schedule_autosave)

        self.total=QLabel();self.total.setWordWrap(True);self.total.setStyleSheet("font-size:17px;font-weight:700;color:#0B2342;padding:6px 2px");box.addWidget(self.total)
        buttons=QDialogButtonBox(QDialogButtonBox.Close);buttons.rejected.connect(self.reject);box.addWidget(buttons);self.refresh()

    def refresh(self):
        p=self.service.get(self.proposal_id)
        if not p:return
        self.heading.setText(f"{p.number} - revisie {p.revision} - {p.title} - {p.customer_name}");self.status.blockSignals(True);self.status.setCurrentText(p.status);self.status.blockSignals(False)
        all_lines=self.service.lines(self.proposal_id);selected_group=self.group_filter.currentData();groups=[]
        for line in all_lines:
            if line.group_name and line.group_name not in groups:groups.append(line.group_name)
        self.group_filter.blockSignals(True);self.group_filter.clear();self.group_filter.addItem("Alle hoofdstukken",None)
        for name in groups:self.group_filter.addItem(name,name)
        if selected_group:
            index=self.group_filter.findData(selected_group)
            if index>=0:self.group_filter.setCurrentIndex(index)
        self.group_filter.blockSignals(False);current_group=self.group_filter.currentData();lines=[x for x in all_lines if not current_group or x.group_name==current_group];self.table.setRowCount(len(lines))
        for r,x in enumerate(lines):
            for c,v in enumerate(("Ja" if x.active else "Nee","Ja" if x.optional else "Nee",x.group_name,x.kind,x.description,f"{x.quantity:g}",x.billing_period,money(x.unit_price_cents),money(x.line_total_cents),str(x.id))):self.table.setItem(r,c,QTableWidgetItem(v))
        t=self.service.totals(self.proposal_id);monthly=self.service.monthly_total(self.proposal_id);self.total.setText(f"Eenmalig excl. btw: {money(t['subtotal_cents'])}  |  incl. btw: {money(t['total_cents'])}  |  maandelijks excl. btw: {money(monthly)}")
        option_count=len([x for x in all_lines if x.active and x.optional]);self.once_total.setText(f"EENMALIG\n{money(t['subtotal_cents'])} excl. btw");self.month_total.setText(f"PER MAAND\n{money(monthly)} excl. btw");self.line_count.setText(f"OFFERTEREGELS\n{len([x for x in all_lines if x.active])} actief · {option_count} optie(s)")
        group_totals=self.service.group_totals(self.proposal_id);self.total.setToolTip("\n".join(f"{name}: {money(values['eenmalig'])} eenmalig · {money(values['maandelijks'])} p/m" for name,values in group_totals.items()))
        if current_group and current_group in group_totals:
            values=group_totals[current_group];self.group_subtotal.setText(f"Subtotaal {money(values['eenmalig'])} · {money(values['maandelijks'])} p/m")
        else:self.group_subtotal.setText(f"{len(group_totals)} hoofdstukken")

    def _selected(self):
        row=self.table.currentRow();item=self.table.item(row,9) if row>=0 else None;return int(item.text()) if item else None
    def _status(self,value):self.service.set_status(self.proposal_id,value);self.refresh()
    def _add(self):
        try:self.service.add_line(self.proposal_id,self.kind.currentText(),self.description.text(),self.quantity.value(),round(self.price.value()*100),self.period.currentText(),self.group.text(),self.optional.isChecked());self.editing_line_id=None;self.description.clear();self.optional.setChecked(False);self.refresh()
        except Exception as e:QMessageBox.warning(self,"Offerteregel",str(e))
    def _load_selected(self,*_):
        line_id=self._selected()
        if not line_id:return
        line=next(x for x in self.service.lines(self.proposal_id) if x.id==line_id);self._loading_form=True;self.editing_line_id=line_id
        self.group.setText(line.group_name);self.kind.setCurrentText(line.kind);self.description.setText(line.description);self.quantity.setValue(line.quantity);self.period.setCurrentText(line.billing_period);self.price.setValue(line.unit_price_cents/100);self.optional.setChecked(bool(line.optional));self._loading_form=False;self.save_state.setText("Regel geopend · wijzigingen worden automatisch opgeslagen")
    def _update(self):
        line_id=self._selected()
        if not line_id:QMessageBox.information(self,"Offerteregel","Selecteer eerst een regel.");return
        try:self.service.update_line(line_id,self.kind.currentText(),self.description.text(),self.quantity.value(),round(self.price.value()*100),self.period.currentText(),self.group.text(),self.optional.isChecked());self.refresh()
        except Exception as e:QMessageBox.warning(self,"Offerteregel",str(e))
    def _duplicate_line(self):
        if self._selected():self.service.duplicate_line(self._selected());self.refresh()
    def _delete(self):
        if self._selected():self.service.delete_line(self._selected());self.refresh()
    def _toggle(self):
        line_id=self._selected()
        if line_id:
            line=next(x for x in self.service.lines(self.proposal_id) if x.id==line_id);self.service.set_line_active(line_id,not bool(line.active));self.refresh()
    def _move(self,direction):
        if self._selected():self.service.move_line(self._selected(),direction);self.refresh()
    def _schedule_autosave(self,*_):
        if self.editing_line_id and not self._loading_form:
            self.save_state.setText("Wijzigingen opslaan…");self.autosave.start()
    def _autosave_selected(self):
        if not self.editing_line_id or not self.description.text().strip():return
        try:
            self.service.update_line(self.editing_line_id,self.kind.currentText(),self.description.text(),self.quantity.value(),round(self.price.value()*100),self.period.currentText(),self.group.text(),self.optional.isChecked());self.save_state.setText("Alle wijzigingen lokaal opgeslagen");self.refresh()
        except Exception as e:self.save_state.setText("Opslaan niet gelukt");QMessageBox.warning(self,"Automatisch opslaan",str(e))
    def _toggle_fullscreen(self):
        if self.isFullScreen():self.showMaximized();self.fullscreen.setText("Volledig scherm")
        else:self.showFullScreen();self.fullscreen.setText("Venster herstellen")
    def _reload_catalog(self):
        self.catalog.clear();self.catalog.addItem("Kies product of dienst...",None)
        for x in self.service.catalog():self.catalog.addItem(f"{x['code']} - {x['name']} ({money(x['unit_price_cents'])})",x["id"])
    def _add_catalog(self):
        if self.catalog.currentData():self.service.add_catalog_line(self.proposal_id,self.catalog.currentData(),self.quantity.value());self.refresh()
    def _apply_template(self):
        try:
            if self.template.currentData():self.service.apply_template(self.proposal_id,self.template.currentData());self.refresh()
        except Exception as e:QMessageBox.warning(self,"Sjabloon",str(e))
    def _sections(self):
        dialog=QDialog(self);dialog.setWindowTitle("Offertehoofdstukken");dialog.resize(820,620);layout=QVBoxLayout(dialog);tabs=QTabWidget();editors={};current=self.service.sections(self.proposal_id)
        for key,title in self.service.SECTION_TITLES.items():editor=QTextEdit();editor.setPlainText(current.get(key,""));editors[key]=editor;tabs.addTab(editor,title)
        layout.addWidget(tabs);buttons=QDialogButtonBox(QDialogButtonBox.Save|QDialogButtonBox.Cancel);buttons.accepted.connect(dialog.accept);buttons.rejected.connect(dialog.reject);layout.addWidget(buttons)
        if dialog.exec():self.service.save_sections(self.proposal_id,{k:e.toPlainText() for k,e in editors.items()});self.refresh()
    def _assets(self):
        try:r=self.service.add_customer_assets(self.proposal_id);self.refresh();QMessageBox.information(self,"Klantdossier",f"Toegevoegd: {r['licenses']} licenties en {r['hardware']} hardware-regels.")
        except Exception as e:QMessageBox.warning(self,"Klantdossier",str(e))
    def _calculate(self):
        if QMessageBox.question(self,"Intakecalculatie","Automatisch berekende uren opnieuw opbouwen?")!=QMessageBox.Yes:return
        try:hours=self.service.calculate_from_intake(self.proposal_id);self.refresh();QMessageBox.information(self,"Intakecalculatie",f"Berekend: {hours:g} uur.")
        except Exception as e:QMessageBox.warning(self,"Intakecalculatie",str(e))
    def _revision(self):
        label,ok=QInputDialog.getText(self,"Nieuwe revisie","Omschrijving van de wijziging")
        if ok:r=self.service.create_revision(self.proposal_id,label);self.refresh();QMessageBox.information(self,"Revisie",f"Revisie {r} is bewaard.")
    def _revision_history(self):
        revisions=self.service.revisions(self.proposal_id);dialog=QDialog(self);dialog.setWindowTitle("Revisiegeschiedenis");dialog.resize(680,420);layout=QVBoxLayout(dialog)
        info=QLabel("Een revisie terugzetten vervangt de huidige regels en hoofdstukken. Eerst wordt automatisch een back-up gemaakt.");info.setWordWrap(True);layout.addWidget(info)
        table=QTableWidget(len(revisions),4);table.setHorizontalHeaderLabels(["Revisie","Omschrijving","Bewaard op","ID"]);table.setColumnHidden(3,True);table.horizontalHeader().setStretchLastSection(True)
        for row,item in enumerate(revisions):
            for column,value in enumerate((str(item["revision_number"]),item["label"] or "Zonder omschrijving",item["created_at"],str(item["id"]))):table.setItem(row,column,QTableWidgetItem(value))
        layout.addWidget(table,1);buttons=QHBoxLayout();restore=QPushButton("Geselecteerde revisie terugzetten");close=QPushButton("Sluiten");buttons.addStretch();buttons.addWidget(restore);buttons.addWidget(close);layout.addLayout(buttons);close.clicked.connect(dialog.reject)
        def do_restore():
            row=table.currentRow();item=table.item(row,3) if row>=0 else None
            if not item:return
            if QMessageBox.question(dialog,"Revisie terugzetten","De huidige offerte wordt eerst veilig als nieuwe revisie bewaard. Doorgaan?")!=QMessageBox.Yes:return
            try:self.service.restore_revision(self.proposal_id,int(item.text()));dialog.accept();self.refresh();QMessageBox.information(self,"Revisie teruggezet","De gekozen revisie is hersteld. De vorige toestand staat in de revisiegeschiedenis.")
            except Exception as e:QMessageBox.warning(dialog,"Revisie terugzetten",str(e))
        restore.clicked.connect(do_restore);dialog.exec()
    def _pdf(self):
        try:
            warnings=self.service.validate(self.proposal_id)
            if warnings and QMessageBox.question(self,"Offertecontrole","Let op:\n\n"+"\n".join("- "+x for x in warnings)+"\n\nToch doorgaan?")!=QMessageBox.Yes:return
            path=export_proposal_pdf(self.service,self.proposal_id)
            if QMessageBox.question(self,"Voorbeeld gereed",f"PDF opgeslagen:\n{path}\n\nNu openen?")==QMessageBox.Yes:QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as e:QMessageBox.warning(self,"PDF export",str(e))
    def _online_approval(self):
        history=self.approvals.history(self.proposal_id)
        active=next((x for x in history if x["status"] in ("voorbereid","gepubliceerd")),None)
        accepted=next((x for x in history if x["status"]=="geaccepteerd" and not x["applied_at"]),None)
        choices=["Nieuw akkoordportaal voorbereiden","Akkoordbestand importeren","Publicatiehistorie bekijken"]
        if active:choices.insert(1,"Actieve publicatie intrekken")
        if accepted:choices.insert(1,"Geaccepteerde licentiewijzigingen verwerken")
        choice,ok=QInputDialog.getItem(self,"Online akkoord","Actie",choices,0,False)
        if not ok:return
        if choice=="Geaccepteerde licentiewijzigingen verwerken":
            if QMessageBox.question(self,"Licenties verwerken","De gecontroleerde aantallen worden nu in het lokale klantdossier verwerkt. Doorgaan?")!=QMessageBox.Yes:return
            try:
                result=self.approvals.apply_license_changes(accepted["id"])
                QMessageBox.information(self,"Licenties verwerkt",f"{result['changed']} licentiewijziging(en) zijn lokaal verwerkt.")
            except Exception as e:QMessageBox.warning(self,"Licenties verwerken",str(e))
            return
        if choice=="Actieve publicatie intrekken":
            try:self.approvals.revoke(active["id"]);QMessageBox.information(self,"Online akkoord","De actieve publicatie is lokaal ingetrokken.")
            except Exception as e:QMessageBox.warning(self,"Online akkoord",str(e))
            return
        if choice=="Akkoordbestand importeren":
            path,_=QFileDialog.getOpenFileName(self,"Akkoordbestand kiezen","","NOWA akkoord (*.json)")
            if not path:return
            try:
                result=self.approvals.import_decision(path)
                changes=[x for x in result["license_changes"] if x["difference"]]
                detail="\n".join(f"• {x['product']}: {x['current_quantity']} → {x['requested_quantity']} ({x['difference']:+d})" for x in changes) or "Geen licentiewijzigingen."
                QMessageBox.information(self,"Akkoord gecontroleerd",f"Akkoord van {result['accepted_by']} is geldig.\n\n{detail}\n\nVerwerk de wijzigingen daarna via Online akkoord.")
            except Exception as e:QMessageBox.warning(self,"Akkoord importeren",str(e))
            return
        if choice=="Publicatiehistorie bekijken":
            text="\n".join(f"R{x['revision']} · {x['status']} · vervalt {x['expires_at']} · {x['accepted_by'] or x['recipient_email'] or 'geen naam/e-mail'}"+(" · verwerkt" if x["applied_at"] else "") for x in history) or "Nog geen akkoordportalen."
            QMessageBox.information(self,"Publicatiehistorie",text);return
        email,ok=QInputDialog.getText(self,"Online akkoord","E-mailadres ontvanger (optioneel)")
        if not ok:return
        from datetime import date,timedelta
        expiry,ok=QInputDialog.getText(self,"Online akkoord","Geldig tot (jjjj-mm-dd)",text=(date.today()+timedelta(days=14)).isoformat())
        if not ok:return
        try:
            result=self.approvals.prepare(self.proposal_id,email,expiry)
            if QMessageBox.question(self,"Akkoordportaal gereed",f"Het zelfstandige akkoordportaal is lokaal gemaakt:\n\n{result['path']}\n\nEr is niets naar internet gestuurd. Openen om te controleren?")==QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(result["path"])))
        except Exception as e:QMessageBox.warning(self,"Online akkoord",str(e))

    def _send_proposal(self):
        try:
            defaults=self.delivery.defaults(self.proposal_id)
        except Exception as exc:
            QMessageBox.warning(self,"Offerte verzenden",str(exc));return
        recipient,ok=QInputDialog.getText(
            self,"Offerte verzenden","Ontvanger",text=defaults["recipient"])
        if not ok:return
        from datetime import date,timedelta
        expiry,ok=QInputDialog.getText(
            self,"Offerte verzenden","Akkoord geldig tot (jjjj-mm-dd)",
            text=(date.today()+timedelta(days=14)).isoformat())
        if not ok:return
        try:
            result=self.delivery.prepare(self.proposal_id,recipient,expiry)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(result["eml_path"])))
            answer=QMessageBox.question(
                self,"Outlook-concept gereed",
                f"Het concept is geopend vanuit {result['sender']} naar {result['recipient']}.\n\n"
                "Bijgevoegd zijn de offerte-PDF en het digitale akkoord.\n\n"
                "Heb je het bericht in Outlook verzonden?")
            if answer==QMessageBox.Yes:
                self.delivery.mail.mark_sent(result["message_id"])
                self.service.set_status(self.proposal_id,"verzonden")
                self.refresh()
        except Exception as exc:
            QMessageBox.warning(self,"Offerte verzenden",str(exc))
