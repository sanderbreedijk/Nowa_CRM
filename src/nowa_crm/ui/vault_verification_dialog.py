from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QFrame, QLabel, QTextEdit, QVBoxLayout)


class VaultVerificationDialog(QDialog):
    """Eén rustig en controleerbaar scherm voor een telefonisch wachtwoordverzoek."""

    def __init__(self, entry: dict, call: dict, contacts, methods, parent=None):
        super().__init__(parent);self.setWindowTitle("Veilige verstrekking controleren");self.setMinimumSize(720,620)
        root=QVBoxLayout(self);root.setContentsMargins(24,22,24,20);root.setSpacing(14)
        title=QLabel("Wachtwoordverzoek veilig afhandelen");title.setObjectName("Title");root.addWidget(title)
        intro=QLabel("Doorloop alle controles in één scherm. Het wachtwoord zelf wordt nooit in het logboek opgeslagen.");intro.setObjectName("Subtitle");intro.setWordWrap(True);root.addWidget(intro)
        context=QFrame();context.setObjectName("CustomerHero");context_box=QVBoxLayout(context)
        context_title=QLabel(f"{entry['customer_name']}  ·  {entry['label']}");context_title.setObjectName("CustomerName");context_box.addWidget(context_title)
        context_box.addWidget(QLabel(f"Beller: {call.get('contact_name') or 'Onbekende contactpersoon'}  ·  {call.get('phone_number','')}"));root.addWidget(context)
        form=QFormLayout();form.setVerticalSpacing(11);self.requester=QComboBox();self.requester.setEditable(True);self.requester.setPlaceholderText("Naam van de aanvrager")
        for contact in contacts:self.requester.addItem(f"{contact.name} — {contact.role or 'contactpersoon'}",contact.name)
        if call.get("contact_name"):
            index=next((i for i in range(self.requester.count()) if self.requester.itemData(i)==call["contact_name"]),-1)
            if index>=0:self.requester.setCurrentIndex(index)
            else:self.requester.setEditText(call["contact_name"])
        self.method=QComboBox();self.method.addItems(methods);self.reason=QTextEdit();self.reason.setPlaceholderText("Waarom heeft deze persoon dit specifieke gegeven nodig?");self.reason.setMaximumHeight(90)
        self.delivery=QComboBox();self.delivery.addItem("Alleen tonen en spellen","show");self.delivery.addItem("Tonen en 30 seconden kopiëren","copy")
        form.addRow("Aanvrager",self.requester);form.addRow("Verificatiemethode",self.method);form.addRow("Reden",self.reason);form.addRow("Wijze van verstrekking",self.delivery);root.addLayout(form)
        checks=QFrame();checks.setObjectName("Card");check_box=QVBoxLayout(checks);head=QLabel("Verplichte bevestigingen");head.setObjectName("SectionTitle");check_box.addWidget(head)
        self.identity=QCheckBox("De identiteit is gecontroleerd via de gekozen methode");self.authority=QCheckBox("Deze persoon is bevoegd voor dit specifieke kluisitem")
        self.customer_match=QCheckBox("De herkende beller en het kluisitem horen bij dezelfde klant");self.customer_match.setChecked(call.get("customer_id")==entry.get("customer_id"));self.customer_match.setEnabled(False)
        check_box.addWidget(self.identity);check_box.addWidget(self.authority);check_box.addWidget(self.customer_match);root.addWidget(checks)
        self.warning=QLabel();self.warning.setObjectName("AttentionBanner");self.warning.setWordWrap(True);root.addWidget(self.warning);root.addStretch()
        self.buttons=QDialogButtonBox(QDialogButtonBox.Ok|QDialogButtonBox.Cancel);self.buttons.button(QDialogButtonBox.Ok).setText("Controle afronden en tonen");self.buttons.accepted.connect(self.accept);self.buttons.rejected.connect(self.reject);root.addWidget(self.buttons)
        self.identity.toggled.connect(self._validate);self.authority.toggled.connect(self._validate);self.requester.currentTextChanged.connect(self._validate);self.reason.textChanged.connect(self._validate);self._validate()

    def _validate(self):
        complete=bool(self.requester.currentText().strip() and len(self.reason.toPlainText().strip())>=5 and self.identity.isChecked() and self.authority.isChecked() and self.customer_match.isChecked())
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(complete)
        if not self.customer_match.isChecked():self.warning.setText("Geblokkeerd: de beller hoort niet bij de klant van dit kluisitem.")
        elif not complete:self.warning.setText("Vul de aanvrager en reden in en bevestig zowel identiteit als bevoegdheid.")
        else:self.warning.setText("Alle controles zijn compleet. De inzage wordt lokaal vastgelegd.")

    @property
    def requester_name(self):return self.requester.currentData() or self.requester.currentText().strip()
    @property
    def request_reason(self):return self.reason.toPlainText().strip()
    @property
    def delivery_mode(self):return self.delivery.currentData()
