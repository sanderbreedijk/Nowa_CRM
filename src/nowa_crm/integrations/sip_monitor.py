from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QAbstractSocket, QHostAddress, QHostInfo, QUdpSocket


class SipMonitor(QObject):
    """Audio-loze SIP/UDP-monitor die REGISTER en inkomende INVITE ondersteunt."""

    event_received = Signal(dict)
    state_changed = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.socket = QUdpSocket(self)
        self.socket.readyRead.connect(self._read)
        self.renew = QTimer(self);self.renew.timeout.connect(self._register)
        self.config = {};self.call_id=f"nowa-{uuid4().hex}";self.cseq=0;self.challenge={}

    @property
    def running(self) -> bool:
        return self.socket.state() == QAbstractSocket.SocketState.BoundState

    def start(self, config: dict) -> bool:
        self.stop();self.config=dict(config);local_port=int(config.get("local_port") or 5080)
        if str(config.get("transport","UDP")).upper()!="UDP":
            self.state_changed.emit("fout","Deze luistermonitor ondersteunt momenteel SIP over UDP.");return False
        ok=self.socket.bind(QHostAddress.SpecialAddress.AnyIPv4,local_port,
            QAbstractSocket.BindFlag.ShareAddress|QAbstractSocket.BindFlag.ReuseAddressHint)
        if not ok:self.state_changed.emit("fout",self.socket.errorString());return False
        self.state_changed.emit("luistert",f"Lokale SIP-poort {local_port} · geen audio")
        if config.get("server") and config.get("username"):self._register()
        return True

    def stop(self) -> None:
        self.renew.stop()
        if self.socket.state()!=QAbstractSocket.SocketState.UnconnectedState:self.socket.close()

    def _register(self, authorization: str = "") -> None:
        server=str(self.config.get("server","")).strip();username=str(self.config.get("username","")).strip()
        if not server or not username:return
        domain=str(self.config.get("domain") or server).strip();port=int(self.config.get("server_port") or 5080)
        local_port=int(self.config.get("local_port") or 5080);self.cseq+=1
        branch="z9hG4bK"+uuid4().hex[:18];tag=uuid4().hex[:12];uri=f"sip:{domain}"
        headers=[f"REGISTER {uri} SIP/2.0",f"Via: SIP/2.0/UDP 0.0.0.0:{local_port};branch={branch};rport",
            "Max-Forwards: 70",f"From: <sip:{username}@{domain}>;tag={tag}",f"To: <sip:{username}@{domain}>",
            f"Call-ID: {self.call_id}",f"CSeq: {self.cseq} REGISTER",
            f"Contact: <sip:{username}@0.0.0.0:{local_port};transport=udp>","Expires: 300","User-Agent: NOWA-CRM-SIP-Monitor/1.0"]
        if authorization:headers.append(f"Authorization: {authorization}")
        data=("\r\n".join(headers)+"\r\nContent-Length: 0\r\n\r\n").encode()
        address=QHostAddress(server)
        if address.isNull():
            addresses=QHostInfo.fromName(server).addresses()
            if not addresses:self.state_changed.emit("fout",f"SIP-server {server} is niet bereikbaar.");return
            address=addresses[0]
        self.socket.writeDatagram(data,address,port)
        self.state_changed.emit("verbinden",f"Registreren bij {server}:{port}")

    def _read(self) -> None:
        while self.socket.hasPendingDatagrams():
            datagram=self.socket.receiveDatagram();raw=bytes(datagram.data()).decode("utf-8","replace")
            first=raw.splitlines()[0] if raw else "";headers=self._headers(raw)
            if first.startswith("SIP/2.0 401") or first.startswith("SIP/2.0 407"):
                challenge=headers.get("www-authenticate") or headers.get("proxy-authenticate","")
                auth=self._authorization(challenge)
                if auth:self._register(auth)
                else:self.state_changed.emit("fout","SIP-authenticatie-uitdaging kon niet worden verwerkt.")
            elif first.startswith("SIP/2.0 200") and "REGISTER" in headers.get("cseq",""):
                self.state_changed.emit("verbonden","SIP-monitor geregistreerd · alleen oproepsignalering")
                self.renew.start(240000)
            elif first.startswith("INVITE "):
                number,name=self._caller(headers.get("from",""));external=headers.get("call-id",uuid4().hex)
                self.event_received.emit({"phone_number":number,"display_name":name,"external_id":external,
                                          "event":"ringing","source":"sip"})
                self._reply(datagram.senderAddress(),datagram.senderPort(),headers,486,"Busy Here")
            elif first.startswith("OPTIONS "):
                self._reply(datagram.senderAddress(),datagram.senderPort(),headers,200,"OK")

    def _authorization(self,challenge: str) -> str:
        values={key.lower():(quoted or plain) for key,quoted,plain in
                re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))',challenge)}
        realm=values.get("realm","");nonce=values.get("nonce","")
        username=str(self.config.get("username",""));password=str(self.config.get("password",""))
        domain=str(self.config.get("domain") or self.config.get("server",""));uri=f"sip:{domain}"
        if not all((realm,nonce,username,password)):return ""
        ha1=hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
        ha2=hashlib.md5(f"REGISTER:{uri}".encode()).hexdigest()
        response=hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
        return f'Digest username="{username}", realm="{realm}", nonce="{nonce}", uri="{uri}", response="{response}", algorithm=MD5'

    @staticmethod
    def _headers(raw: str) -> dict:
        result={}
        for line in raw.replace("\r\n "," ").splitlines()[1:]:
            if ":" in line:
                key,value=line.split(":",1);result[key.strip().lower()]=value.strip()
        return result

    @staticmethod
    def _caller(from_header: str) -> tuple[str,str]:
        match=re.search(r'(?:"([^"]*)"\s*)?<sip:([^@;>]+)',from_header,re.I)
        return (match.group(2),match.group(1) or "") if match else ("","")

    def _reply(self,address,port,headers: dict,code: int,reason: str) -> None:
        to=headers.get("to","")
        if ";tag=" not in to:to+=f";tag={uuid4().hex[:10]}"
        lines=[f"SIP/2.0 {code} {reason}",f"Via: {headers.get('via','')}",f"From: {headers.get('from','')}",
               f"To: {to}",f"Call-ID: {headers.get('call-id','')}",f"CSeq: {headers.get('cseq','')}",
               "Server: NOWA-CRM-SIP-Monitor/1.0","Content-Length: 0","",""]
        self.socket.writeDatagram("\r\n".join(lines).encode(),address,port)
