"""Agente do Raspberry Pi: controla as mesas localmente e se comunica com o PC de IA e com a VM.

- Cada mesa roda o modo Math no proprio Pi (camera -> deteccao -> Arduino), sem depender da rede.
- Um PC na rede local pode assumir uma mesa no modo IA (main.py --pi). O Pi envia os quadros e
  repassa os comandos ao Arduino. Se o PC parar de responder, a mesa volta ao Math sozinha.
- O Pi abre uma conexao TLS de saida para o servidor (VM) e envia placar, status e video reduzido.
  A VM so pode zerar o placar; ela nunca aciona os solenoides.

Uso: python pi_agente.py --config pi.json
Tokens: variaveis de ambiente PINBALL_TOKEN_LAN e PINBALL_TOKEN_VM (ou os nomes em token_env).
"""
import argparse
import json
import logging
import os
import select
import socket
import ssl
import threading
import time

import cv2

import config
import protocolo
from arduino import Arduino, MODO_MANUAL
from camera import abrirCamera, lerQuadro
from controle import ControleMesa
from desenho import desenharPlacar

log = logging.getLogger("pi_agente")

PADRAO = {
    "mesas": [],
    "lan": {"endereco": "0.0.0.0", "porta": 5800, "token_env": "PINBALL_TOKEN_LAN",
            "jpeg_qualidade": 80, "timeout_s": 1.0},
    "vm": None,
}
PADRAO_VM = {"porta": 8443, "token_env": "PINBALL_TOKEN_VM", "ca": None, "nome_servidor": None,
             "fps": 10, "largura": 640, "jpeg_qualidade": 70}


def carregarConfigPi(caminho):
    with open(caminho, encoding="utf-8") as f:
        dados = json.load(f)
    cfg = {"mesas": dados.get("mesas", []), "lan": dict(PADRAO["lan"], **dados.get("lan", {})), "vm": None}
    if dados.get("vm"):
        cfg["vm"] = dict(PADRAO_VM, **dados["vm"])
    base = os.path.dirname(os.path.abspath(caminho))
    for m in cfg["mesas"]:
        m["config"] = os.path.join(base, m.get("config", "config_mesa%d.json" % m["id"]))
    if cfg["vm"] and cfg["vm"]["ca"]:
        cfg["vm"]["ca"] = os.path.join(base, cfg["vm"]["ca"])
    return cfg


def lerToken(secao):
    token = os.environ.get(secao.get("token_env", ""), "") or secao.get("token", "")
    return token or None


def codificarJpeg(image, qualidade, largura=None):
    if largura and image.shape[1] > largura:
        altura = int(image.shape[0] * largura / image.shape[1])
        image = cv2.resize(image, (largura, altura), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, int(qualidade)])
    return buf.tobytes() if ok else None


# ---------------------------------------------------------------------------- mesa

class MesaPi(threading.Thread):
    def __init__(self, cfgMesa, lan, cfgVm):
        super().__init__(daemon=True, name="mesa%d" % cfgMesa["id"])
        self.id = int(cfgMesa["id"])
        self.cfgMesa = cfgMesa
        self.cfg = config.carregar(cfgMesa["config"])
        self.ctrl = ControleMesa(self.cfg, lancador=bool(cfgMesa.get("lancador")))
        self.lan = lan
        self.cfgVm = cfgVm
        self.arduino = Arduino(None)
        self._tentativaSerial = float("-inf")
        self.captura = None
        self.modo = "math"
        self.fps = 0.0
        self.latenciaMs = None
        self._vmLock = threading.Lock()
        self._vmJpeg = None
        self._vmVersao = 0
        self.parar = False

    # --- recursos
    def _abrirArduino(self, agora):
        if self.arduino.ativo or agora - self._tentativaSerial < 5:
            return
        self._tentativaSerial = agora
        try:
            self.arduino = Arduino(self.cfgMesa["porta"], self.cfgMesa.get("baud", 115200))
            log.info("mesa %d: Arduino conectado em %s", self.id, self.cfgMesa["porta"])
        except Exception as e:  # porta ausente, permissao, etc.
            log.warning("mesa %d: Arduino indisponivel (%s); nova tentativa em 5 s", self.id, e)

    def _abrirCamera(self):
        cam = self.cfgMesa["camera"]
        cam = int(cam) if isinstance(cam, int) or str(cam).isdigit() else cam
        self.captura = abrirCamera(cam, self.cfg["camera"], sairSeFalhar=False)
        if self.captura is None:
            log.warning("mesa %d: camera %s indisponivel; nova tentativa em 2 s", self.id, cam)
        else:
            log.info("mesa %d: camera %s aberta", self.id, cam)

    # --- ciclo principal
    def run(self):
        ultimoVm = float("-inf")
        anterior = None
        falhas = 0
        while not self.parar:
            self._abrirArduino(time.monotonic())
            if self.captura is None:
                self._abrirCamera()
                if self.captura is None:
                    time.sleep(2)
                    continue
            image = lerQuadro(self.captura, self.cfg["camera"])
            agora = time.monotonic()
            if image is None:
                falhas += 1
                if falhas > 30:
                    log.warning("mesa %d: camera parou de responder; reabrindo", self.id)
                    self.captura.release()
                    self.captura = None
                    falhas = 0
                continue
            falhas = 0
            if anterior is not None and agora > anterior:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / (agora - anterior))
            anterior = agora

            if self.arduino.ativo:
                try:
                    self.arduino.atualizar(agora)
                except Exception as e:
                    log.warning("mesa %d: erro na serial (%s); reconectando", self.id, e)
                    self.arduino.fechar()
                    self.arduino = Arduino(None)

            if self.lan is not None and self.lan.controlando(self.id, agora):
                if self.modo != "ia":
                    log.info("mesa %d: PC de IA assumiu o controle", self.id)
                    self.modo = "ia"
                self.lan.publicarQuadro(self.id, image, agora)
            else:
                if self.modo == "ia":
                    log.info("mesa %d: PC de IA saiu; voltando ao modo Math", self.id)
                    self.modo = "math"
                    self.ctrl.reiniciar()
                for c in self.ctrl.processar(image, agora, permitirDisparo=self.arduino.modo != MODO_MANUAL):
                    self.arduino.enviar(c)

            if self.cfgVm and agora - ultimoVm >= 1.0 / self.cfgVm["fps"]:
                ultimoVm = agora
                self._prepararVm(image, agora)

        if self.captura is not None:
            self.captura.release()
        self.arduino.fechar()

    def _prepararVm(self, image, agora):
        img = image.copy()
        if self.modo == "math":
            self.ctrl.desenhar(img, "Math (Pi)", "%d" % self.fps)
        else:
            cv2.putText(img, "IA (PC)", (0, 70), cv2.FONT_HERSHEY_SIMPLEX, 1, (100, 255, 0), 2, cv2.LINE_AA)
        desenharPlacar(img, self.arduino, agora)
        jpeg = codificarJpeg(img, self.cfgVm["jpeg_qualidade"], self.cfgVm["largura"])
        with self._vmLock:
            self._vmJpeg = jpeg
            self._vmVersao += 1

    def quadroVm(self):
        with self._vmLock:
            return self._vmVersao, self._vmJpeg

    # --- comandos vindos da rede
    def comandoRemoto(self, c, tQuadro):
        """Comando do PC de IA (so vale enquanto ele controla a mesa)."""
        if c == "r":
            self.arduino.zerarPlacar()
            return
        if c not in ("1", "2", "3") or self.modo != "ia" or self.arduino.modo == MODO_MANUAL:
            return
        self.arduino.enviar(c.encode("ascii"))
        if isinstance(tQuadro, (int, float)):
            lat = (time.monotonic() - tQuadro) * 1000.0
            self.latenciaMs = lat if self.latenciaMs is None else 0.8 * self.latenciaMs + 0.2 * lat

    def comandoAdmin(self, c):
        """Comando da VM: somente zerar o placar."""
        if c == "r":
            self.arduino.zerarPlacar()

    def status(self, agora):
        a = self.arduino
        return {"tipo": "status", "mesa": self.id, "t": agora, "modo": self.modo,
                "fps": round(self.fps, 1),
                "latencia_ms": round(self.latenciaMs) if self.latenciaMs is not None else None,
                "camera": self.captura is not None,
                "arduino": {"conectado": a.conectado(agora), "serial": a.ativo, "modo": a.modo,
                            "total": a.total, "grupos": a.grupos,
                            "ultimo_impacto": list(a.ultimoImpacto) if a.ultimoImpacto else None}}


# ---------------------------------------------------------------------------- PC de IA (rede local)

class ClienteIa:
    def __init__(self, sock, mesa, qualidade):
        self.sock = sock
        self.mesa = mesa
        self.qualidade = qualidade
        self.ultimo = time.monotonic()
        self.ativo = True
        self._cond = threading.Condition()
        self._quadro = None

    def definirQuadro(self, image, t):
        jpeg = codificarJpeg(image, self.qualidade)
        with self._cond:
            self._quadro = (jpeg, t, image.shape[1], image.shape[0])
            self._cond.notify()

    def enviarLoop(self):
        """Envia o quadro mais recente (sem fila) e o status da mesa a cada 250 ms."""
        ultimoStatus = 0.0
        try:
            while self.ativo:
                with self._cond:
                    self._cond.wait_for(lambda: self._quadro is not None or not self.ativo, 0.25)
                    quadro, self._quadro = self._quadro, None
                if quadro and quadro[0]:
                    jpeg, t, w, h = quadro
                    protocolo.enviar(self.sock, {"tipo": "quadro", "mesa": self.mesa.id, "t": t,
                                                 "largura": w, "altura": h}, jpeg)
                agora = time.monotonic()
                if agora - ultimoStatus >= 0.25:
                    ultimoStatus = agora
                    protocolo.enviar(self.sock, self.mesa.status(agora))
        except OSError:
            pass
        finally:
            self.ativo = False


class ServidorLan(threading.Thread):
    def __init__(self, cfgLan, token, mesas):
        super().__init__(daemon=True, name="lan")
        self.cfg = cfgLan
        self.token = token
        self.mesas = mesas
        self.timeout = float(cfgLan["timeout_s"])
        self.clientes = {}
        self._lock = threading.Lock()
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((cfgLan["endereco"], int(cfgLan["porta"])))
        self.sock.listen(4)

    def run(self):
        log.info("aguardando PC de IA em %s:%s", self.cfg["endereco"], self.cfg["porta"])
        while True:
            conn, endereco = self.sock.accept()
            threading.Thread(target=self._atender, args=(conn, endereco), daemon=True).start()

    def controlando(self, mesaId, agora):
        with self._lock:
            c = self.clientes.get(mesaId)
        return c is not None and c.ativo and time.monotonic() - c.ultimo < self.timeout

    def publicarQuadro(self, mesaId, image, t):
        with self._lock:
            c = self.clientes.get(mesaId)
        if c is not None and c.ativo:
            c.definirQuadro(image, t)

    def _atender(self, conn, endereco):
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        conn.settimeout(5)
        cliente = None
        try:
            cab, _ = protocolo.receber(conn)
            mesa = self.mesas.get(cab.get("mesa"))
            if cab.get("tipo") != "hello" or cab.get("papel") != "ia" or not protocolo.tokenValido(cab.get("token"), self.token):
                protocolo.enviar(conn, {"tipo": "erro", "motivo": "acesso negado"})
                log.warning("PC de IA recusado (%s): token ou hello invalido", endereco[0])
                return
            if mesa is None:
                protocolo.enviar(conn, {"tipo": "erro", "motivo": "mesa inexistente"})
                return
            with self._lock:
                atual = self.clientes.get(mesa.id)
                if atual is not None and atual.ativo:
                    protocolo.enviar(conn, {"tipo": "erro", "motivo": "mesa ja controlada por outro PC"})
                    return
                cliente = ClienteIa(conn, mesa, self.cfg["jpeg_qualidade"])
                self.clientes[mesa.id] = cliente
            protocolo.enviar(conn, {"tipo": "ok", "mesa": mesa.id, "config": mesa.cfg})
            log.info("PC de IA %s conectado a mesa %d", endereco[0], mesa.id)
            conn.settimeout(max(2.0, 3 * self.timeout))
            threading.Thread(target=cliente.enviarLoop, daemon=True).start()
            while cliente.ativo:
                cab, _ = protocolo.receber(conn)
                cliente.ultimo = time.monotonic()
                if cab["tipo"] == "cmd":
                    mesa.comandoRemoto(str(cab.get("c", "")), cab.get("t"))
        except (OSError, ConnectionError, protocolo.ErroProtocolo, ValueError) as e:
            if cliente is not None:
                log.info("PC de IA da mesa %d desconectado (%s)", cliente.mesa.id, e)
        finally:
            if cliente is not None:
                cliente.ativo = False
                with cliente._cond:
                    cliente._cond.notify()
                with self._lock:
                    if self.clientes.get(cliente.mesa.id) is cliente:
                        del self.clientes[cliente.mesa.id]
            conn.close()


# ---------------------------------------------------------------------------- servidor (VM)

class UplinkVm(threading.Thread):
    """Conexao TLS de saida para a VM. Reconecta sozinha com espera crescente."""

    def __init__(self, cfgVm, token, mesas):
        super().__init__(daemon=True, name="vm")
        self.cfg = cfgVm
        self.token = token
        self.mesas = mesas

    def run(self):
        espera = 2
        while True:
            try:
                self._sessao()
                espera = 2
            except (OSError, ssl.SSLError, ConnectionError, protocolo.ErroProtocolo, ValueError) as e:
                log.warning("conexao com a VM falhou (%s); nova tentativa em %d s", e, espera)
            time.sleep(espera)
            espera = min(espera * 2, 30)

    def _sessao(self):
        host, porta = self.cfg["host"], int(self.cfg["porta"])
        ctx = ssl.create_default_context(cafile=self.cfg["ca"]) if self.cfg["ca"] else ssl.create_default_context()
        bruto = socket.create_connection((host, porta), timeout=10)
        sock = ctx.wrap_socket(bruto, server_hostname=self.cfg["nome_servidor"] or host)
        try:
            protocolo.enviar(sock, {"tipo": "hello", "papel": "pi", "token": self.token,
                                    "mesas": sorted(self.mesas)})
            cab, _ = protocolo.receber(sock)
            if cab.get("tipo") != "ok":
                raise ConnectionError("VM recusou: %s" % cab.get("motivo", cab))
            log.info("conectado a VM %s:%d", host, porta)
            versoes = {}
            intervalo = 1.0 / self.cfg["fps"]
            proximo = time.monotonic()
            # Uma unica thread le e escreve no socket TLS (o OpenSSL nao e seguro para uso concorrente)
            while True:
                espera = max(0.0, proximo - time.monotonic())
                if sock.pending() or select.select([sock], [], [], espera)[0]:
                    cab, _ = protocolo.receber(sock)
                    if cab["tipo"] == "cmd" and cab.get("mesa") in self.mesas:
                        self.mesas[cab["mesa"]].comandoAdmin(str(cab.get("c", "")))
                    continue
                proximo = time.monotonic() + intervalo
                agora = time.monotonic()
                for mid, mesa in self.mesas.items():
                    protocolo.enviar(sock, mesa.status(agora))
                    versao, jpeg = mesa.quadroVm()
                    if jpeg and versoes.get(mid) != versao:
                        versoes[mid] = versao
                        protocolo.enviar(sock, {"tipo": "quadro", "mesa": mid, "t": agora}, jpeg)
        finally:
            sock.close()


# ---------------------------------------------------------------------------- inicio

def main():
    p = argparse.ArgumentParser(description="Agente das mesas de pinball no Raspberry Pi")
    p.add_argument("--config", default="pi.json")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(threadName)s: %(message)s")

    cfg = carregarConfigPi(args.config)
    if not cfg["mesas"]:
        raise SystemExit("Nenhuma mesa configurada em %s" % args.config)

    tokenLan = lerToken(cfg["lan"])
    lan = None
    mesas = {}
    if tokenLan:
        lan = ServidorLan(cfg["lan"], tokenLan, mesas)
    else:
        log.warning("sem token da rede local (%s): PC de IA desabilitado", cfg["lan"]["token_env"])

    for m in cfg["mesas"]:
        mesa = MesaPi(m, lan, cfg["vm"])
        mesas[mesa.id] = mesa

    if lan:
        lan.start()
    if cfg["vm"]:
        tokenVm = lerToken(cfg["vm"])
        if tokenVm:
            UplinkVm(cfg["vm"], tokenVm, mesas).start()
        else:
            log.warning("sem token da VM (%s): envio para a VM desabilitado", cfg["vm"]["token_env"])
    for mesa in mesas.values():
        mesa.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for mesa in mesas.values():
            mesa.parar = True
        for mesa in mesas.values():
            mesa.join(timeout=3)


if __name__ == "__main__":
    main()
