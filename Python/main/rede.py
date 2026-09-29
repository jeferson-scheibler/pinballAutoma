"""Cliente do PC de IA: recebe os quadros de uma mesa do Raspberry Pi e devolve os comandos.

CameraRemota e ArduinoRemoto tem a mesma interface de camera/Arduino locais usada pelo
main.py. Todos os instantes usam o relogio do Pi (instante da captura do quadro), entao
nao e preciso sincronizar os relogios do PC e do Pi.
"""
import socket
import threading
import time

import cv2
import numpy

import protocolo
from arduino import MODO_AUTOMATICO, MODO_MANUAL

PORTA_PADRAO = 5800


class ConexaoPi:
    def __init__(self, endereco, token, mesa, intervaloPing=0.3):
        host, _, porta = endereco.partition(":")
        self.mesa = mesa
        self.sock = socket.create_connection((host, int(porta or PORTA_PADRAO)), timeout=10)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._lockEnvio = threading.Lock()
        protocolo.enviar(self.sock, {"tipo": "hello", "papel": "ia", "token": token, "mesa": mesa})
        cab, _ = protocolo.receber(self.sock)
        if cab.get("tipo") != "ok":
            self.sock.close()
            raise ConnectionError("Pi recusou a conexao: %s" % cab.get("motivo", cab))
        self.sock.settimeout(None)
        self.config = cab["config"]
        self.ativa = True
        self.camera = CameraRemota()
        self.arduino = ArduinoRemoto(self)
        self.intervaloPing = intervaloPing
        threading.Thread(target=self._receber, daemon=True).start()
        threading.Thread(target=self._pingar, daemon=True).start()

    def enviar(self, cab):
        with self._lockEnvio:
            protocolo.enviar(self.sock, cab)

    def _receber(self):
        try:
            while self.ativa:
                cab, dados = protocolo.receber(self.sock)
                if cab["tipo"] == "quadro":
                    self.camera._novo(dados, cab["t"])
                elif cab["tipo"] == "status":
                    self.arduino._status(cab)
        except (OSError, ConnectionError, protocolo.ErroProtocolo) as e:
            if self.ativa:
                print("Conexao com o Pi encerrada:", e)
        finally:
            self.ativa = False
            self.camera._encerrar()

    def _pingar(self):
        while self.ativa:
            try:
                self.enviar({"tipo": "ping", "mesa": self.mesa})
            except OSError:
                break
            time.sleep(self.intervaloPing)

    def fechar(self):
        self.ativa = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class CameraRemota:
    """Sempre entrega o quadro mais recente; quadros antigos sao descartados (sem fila)."""

    def __init__(self):
        self._cond = threading.Condition()
        self._jpeg = None
        self._t = None
        self._fim = False

    def _novo(self, jpeg, t):
        with self._cond:
            self._jpeg, self._t = jpeg, t
            self._cond.notify()

    def _encerrar(self):
        with self._cond:
            self._fim = True
            self._cond.notify()

    def ler(self, timeout=2.0):
        """Retorna (imagem BGR, instante da captura no relogio do Pi) ou (None, None)."""
        with self._cond:
            if not self._cond.wait_for(lambda: self._jpeg is not None or self._fim, timeout):
                return None, None
            if self._jpeg is None:
                return None, None
            jpeg, t = self._jpeg, self._t
            self._jpeg = None
        img = cv2.imdecode(numpy.frombuffer(jpeg, numpy.uint8), cv2.IMREAD_COLOR)
        return img, t

    def release(self):
        pass


class ArduinoRemoto:
    """Arduino da mesa visto pelo PC: comandos vao para o Pi, status vem do Pi."""

    def __init__(self, conexao):
        self.conexao = conexao
        self.modo = None
        self.total = 0
        self.grupos = [0, 0, 0, 0]
        self.ultimoImpacto = None
        self.latenciaMs = None
        self._conectado = False
        self._tQuadro = None
        self._tStatus = None
        self._tStatusLocal = None

    ativo = True

    def _status(self, cab):
        ard = cab.get("arduino", {})
        self.modo = ard.get("modo")
        self.total = ard.get("total", 0)
        self.grupos = ard.get("grupos", self.grupos)
        self._conectado = bool(ard.get("conectado"))
        self.latenciaMs = cab.get("latencia_ms")
        self._tStatus = cab.get("t")
        self._tStatusLocal = time.monotonic()
        imp = ard.get("ultimo_impacto")
        if imp is not None:
            self.ultimoImpacto = (imp[0], imp[1])   # (sensor, instante no relogio do Pi)

    def usarQuadro(self, t):
        """Informa o instante do quadro em processamento (enviado junto com os comandos)."""
        self._tQuadro = t

    def conectado(self, agora=None):
        recente = self._tStatusLocal is not None and time.monotonic() - self._tStatusLocal < 3.0
        return self.conexao.ativa and recente and self._conectado

    def enviar(self, comando):
        c = comando.decode("ascii") if isinstance(comando, bytes) else comando
        self.conexao.enviar({"tipo": "cmd", "mesa": self.conexao.mesa, "c": c, "t": self._tQuadro})

    def zerarPlacar(self):
        self.enviar("r")

    def atualizar(self, agora=None):
        return []

    def textoStatus(self, agora=None):
        if not self.conexao.ativa:
            return "Pi: DESCONECTADO"
        if not self.conectado():
            return "Arduino: SEM RESPOSTA"
        modo = {MODO_AUTOMATICO: "auto", MODO_MANUAL: "manual"}.get(self.modo, "?")
        lat = " %dms" % self.latenciaMs if self.latenciaMs is not None else ""
        return "Pi/Arduino: %s%s" % (modo, lat)

    def fechar(self):
        self.conexao.fechar()
