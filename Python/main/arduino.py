"""Comunicacao com o Arduino da mesa (protocolo descrito em mesaPinball.ino).

PC -> Arduino: '1' esquerdo, '2' direito, '3' lancador, '?' status, 'r' zera placar.
Arduino -> PC: 'S,<modo>,<total>,<g0>,<g1>,<g2>,<g3>' e 'H,<sensor>,<total>'.
"""
import time

CMD_ESQUERDO = b'1'
CMD_DIREITO = b'2'
CMD_LANCAR = b'3'
CMD_STATUS = b'?'
CMD_ZERAR = b'r'

MODO_AUTOMATICO = 0
MODO_MANUAL = 1


def parseLinha(linha):
    """Converte uma linha recebida em um dicionario, ou None se for invalida."""
    partes = linha.strip().split(",")
    try:
        if partes[0] == "S" and len(partes) == 7:
            valores = [int(v) for v in partes[1:]]
            return {"tipo": "status", "modo": valores[0], "total": valores[1], "grupos": valores[2:]}
        if partes[0] == "H" and len(partes) == 3:
            return {"tipo": "impacto", "sensor": int(partes[1]), "total": int(partes[2])}
    except ValueError:
        pass
    return None


class Arduino:
    """Mantem o estado da mesa sincronizado com o Arduino.

    Pede o status periodicamente; se nenhuma mensagem chegar dentro de `timeout`
    segundos, a conexao e considerada perdida.
    """

    def __init__(self, porta=None, baud=115200, intervaloStatus=1.0, timeout=3.0):
        self.serial = None
        self.intervaloStatus = intervaloStatus
        self.timeout = timeout
        self.modo = None
        self.total = 0
        self.grupos = [0, 0, 0, 0]
        self.ultimoImpacto = None      # (sensor, instante)
        self.ultimaMensagem = None
        self.ultimoPedido = float("-inf")
        self._buffer = b""
        if porta is not None:
            import serial
            self.serial = serial.Serial(porta, baud, timeout=0)
            # O Arduino reinicia ao abrir a porta; aguarda o bootloader antes de enviar comandos
            time.sleep(2)
            self.serial.reset_input_buffer()

    @property
    def ativo(self):
        return self.serial is not None

    def conectado(self, agora=None):
        if self.ultimaMensagem is None:
            return False
        agora = time.monotonic() if agora is None else agora
        return agora - self.ultimaMensagem <= self.timeout

    def enviar(self, comando):
        if self.serial is not None:
            self.serial.write(comando)

    def zerarPlacar(self):
        self.enviar(CMD_ZERAR)

    def processarLinha(self, linha, agora):
        msg = parseLinha(linha)
        if msg is None:
            return None
        self.ultimaMensagem = agora
        self.total = msg["total"]
        if msg["tipo"] == "status":
            self.modo = msg["modo"]
            self.grupos = msg["grupos"]
        else:
            self.ultimoImpacto = (msg["sensor"], agora)
        return msg

    def atualizar(self, agora=None):
        """Le as mensagens pendentes (sem bloquear) e pede status quando necessario.

        Retorna a lista de mensagens recebidas neste ciclo.
        """
        if self.serial is None:
            return []
        agora = time.monotonic() if agora is None else agora
        if agora - self.ultimoPedido >= self.intervaloStatus:
            self.enviar(CMD_STATUS)
            self.ultimoPedido = agora

        pendente = self.serial.in_waiting
        if pendente:
            self._buffer += self.serial.read(pendente)
        mensagens = []
        while b"\n" in self._buffer:
            linha, self._buffer = self._buffer.split(b"\n", 1)
            msg = self.processarLinha(linha.decode("ascii", errors="ignore"), agora)
            if msg is not None:
                mensagens.append(msg)
        return mensagens

    def textoStatus(self, agora=None):
        if self.serial is None:
            return "Arduino: sem serial"
        if not self.conectado(agora):
            return "Arduino: SEM RESPOSTA"
        modo = {MODO_AUTOMATICO: "auto", MODO_MANUAL: "manual"}.get(self.modo, "?")
        return "Arduino: %s" % modo

    def fechar(self):
        if self.serial is not None:
            self.serial.close()
            self.serial = None
