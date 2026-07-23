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
        self.config = {};self.call_id=f"nowa-{uuid4().hex}";self.from_tag=uuid4().hex[:12];self.cseq=0
        self.auth_attempts={};self.total_auth_attempts=0;self.registered=False;self.last_state=("", "")

    @property
    def running(self) -> bool:
        return self.socket.state() in (QAbstractSocket.SocketState.BoundState,QAbstractSocket.SocketState.ConnectedState)

    def start(self, config: dict) -> bool:
        self.stop();self.config=dict(config);self.auth_attempts={};self.total_auth_attempts=0;self.registered=False;self.last_state=("", "")
        local_port=int(config.get("local_port") or 5080)
        if str(config.get("transport","UDP")).upper()!="UDP":
            self._set_state("fout","Deze luistermonitor ondersteunt momenteel SIP over UDP.");return False
        ok=self.socket.bind(QHostAddress.SpecialAddress.AnyIPv4,local_port,
            QAbstractSocket.BindFlag.ShareAddress|QAbstractSocket.BindFlag.ReuseAddressHint)
        if not ok:self._set_state("fout",self.socket.errorString());return False
        self._set_state("luistert",f"Lokale SIP-poort {local_port} · geen audio")
        if config.get("server") and config.get("username"):self._register()
        return True

    def stop(self) -> None:
        self.renew.stop()
        self.registered=False
        if self.socket.state()!=QAbstractSocket.SocketState.UnconnectedState:self.socket.close()

    def _register(self, authorization: str = "", proxy_authorization: bool = False) -> None:
        server=str(self.config.get("server","")).strip();username=str(self.config.get("username","")).strip()
        if not server or not username:return
        domain=str(self.config.get("domain") or server).strip();port=int(self.config.get("server_port") or 5080)
        local_port=int(self.config.get("local_port") or 5080);self.cseq+=1
        address=QHostAddress(server)
        if address.isNull():
            addresses=[item for item in QHostInfo.fromName(server).addresses() if item.protocol()==QAbstractSocket.NetworkLayerProtocol.IPv4Protocol]
            if not addresses:self._set_state("fout",f"SIP-server {server} is niet bereikbaar via IPv4.");return
            address=addresses[0]
        probe=QUdpSocket();probe.connectToHost(address,port);probe.waitForConnected(500)
        local_address=probe.localAddress().toString() or "127.0.0.1";probe.close()
        branch="z9hG4bK"+uuid4().hex[:18];uri=f"sip:{domain}"
        headers=[f"REGISTER {uri} SIP/2.0",f"Via: SIP/2.0/UDP {local_address}:{local_port};branch={branch};rport",
            "Max-Forwards: 70",f"From: <sip:{username}@{domain}>;tag={self.from_tag}",f"To: <sip:{username}@{domain}>",
            f"Call-ID: {self.call_id}",f"CSeq: {self.cseq} REGISTER",
            f"Contact: <sip:{username}@{local_address}:{local_port};transport=udp>","Expires: 300",
            "Allow: INVITE, ACK, CANCEL, BYE, OPTIONS","User-Agent: NOWA-CRM-SIP-Monitor/1.1"]
        if authorization:headers.append(f"{'Proxy-' if proxy_authorization else ''}Authorization: {authorization}")
        data=("\r\n".join(headers)+"\r\nContent-Length: 0\r\n\r\n").encode()
        self.socket.writeDatagram(data,address,port)
        if not self.registered:self._set_state("verbinden",f"Registreren bij {server}:{port}")

    def _read(self) -> None:
        while self.socket.hasPendingDatagrams():
            datagram=self.socket.receiveDatagram();raw=bytes(datagram.data()).decode("utf-8","replace")
            first=raw.splitlines()[0] if raw else "";headers=self._headers(raw)
            if first.startswith("SIP/2.0 401") or first.startswith("SIP/2.0 407"):
                challenge=headers.get("www-authenticate") or headers.get("proxy-authenticate","")
                values=self._challenge_values(challenge);nonce=values.get("nonce","")
                self.total_auth_attempts+=1
                self.auth_attempts[nonce]=self.auth_attempts.get(nonce,0)+1
                if self.total_auth_attempts>3 or (self.auth_attempts[nonce]>1 and values.get("stale","").lower()!="true"):
                    self.renew.stop();self._set_state("fout","SIP-aanmelding geweigerd. Controleer gebruikersnaam, wachtwoord en domein.");continue
                auth=self._authorization(challenge)
                if auth:self._register(auth,first.startswith("SIP/2.0 407"))
                else:self._set_state("fout","SIP-authenticatie-uitdaging kon niet worden verwerkt.")
            elif first.startswith("SIP/2.0 200") and "REGISTER" in headers.get("cseq",""):
                self.registered=True;self.auth_attempts={};self.total_auth_attempts=0
                self._set_state("verbonden","SIP-monitor geregistreerd · alleen oproepsignalering")
                self.renew.start(240000)
            elif first.startswith("SIP/2.0 ") and "REGISTER" in headers.get("cseq",""):
                self.renew.stop();self._set_state("fout",f"SIP-registratie mislukt: {first}")
            elif first.startswith("INVITE "):
                number,name=self._caller(headers.get("from",""));external=headers.get("call-id",uuid4().hex)
                self.event_received.emit({"phone_number":number,"display_name":name,"external_id":external,
                                          "event":"ringing","source":"sip"})
                self._reply(datagram.senderAddress(),datagram.senderPort(),headers,486,"Busy Here")
            elif first.startswith("OPTIONS "):
                self._reply(datagram.senderAddress(),datagram.senderPort(),headers,200,"OK")

    def _authorization(self,challenge: str) -> str:
        values=self._challenge_values(challenge)
        realm=values.get("realm","");nonce=values.get("nonce","")
        username=str(self.config.get("username",""));password=str(self.config.get("password",""))
        domain=str(self.config.get("domain") or self.config.get("server",""));uri=f"sip:{domain}"
        if not all((realm,nonce,username,password)):return ""
        ha1=hashlib.md5(f"{username}:{realm}:{password}".encode()).hexdigest()
        ha2=hashlib.md5(f"REGISTER:{uri}".encode()).hexdigest()
        qop="auth" if "auth" in values.get("qop","").lower().split(",") else ""
        fields=[f'username="{username}"',f'realm="{realm}"',f'nonce="{nonce}"',f'uri="{uri}"']
        if qop:
            nc="00000001";cnonce=uuid4().hex[:16]
            response=hashlib.md5(f"{ha1}:{nonce}:{nc}:{cnonce}:{qop}:{ha2}".encode()).hexdigest()
            fields.extend([f'response="{response}"',f"algorithm={values.get('algorithm','MD5')}",f"qop={qop}",f"nc={nc}",f'cnonce="{cnonce}"'])
        else:
            response=hashlib.md5(f"{ha1}:{nonce}:{ha2}".encode()).hexdigest()
            fields.extend([f'response="{response}"',f"algorithm={values.get('algorithm','MD5')}"])
        if values.get("opaque"):fields.append(f'opaque="{values["opaque"]}"')
        return "Digest "+", ".join(fields)

    @staticmethod
    def _challenge_values(challenge: str) -> dict:
        return {key.lower():(quoted or plain) for key,quoted,plain in
                re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]+))',challenge)}

    def _set_state(self,state: str,detail: str) -> None:
        current=(state,detail)
        if current==self.last_state:return
        self.last_state=current;self.state_changed.emit(state,detail)

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
