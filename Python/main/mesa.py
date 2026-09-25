import time


class HitBox:
    """Retangulo de atuacao. (x, y) e o ponto central superior da caixa."""

    def __init__(self, w=0, h=0):
        self.x = 0
        self.y = 0
        self.w = w
        self.h = h
        self.valid = False


class mesa:
    # Lados retornados por isHit()
    ESQUERDO = 0
    DIREITO = 1
    NENHUM = 99

    def __init__(self, historico=10, cooldown=0.35, cooldownLancador=2.0):
        self.bx = []
        self.by = []
        self.radio = 0
        self.historico = historico
        # Tempo minimo (s) entre dois comandos do mesmo atuador
        self.cooldown = cooldown
        self.cooldownLancador = cooldownLancador
        self._ultimoDisparo = {}

        # Estado por instancia (antes era compartilhado entre instancias)
        self.hb = HitBox(w=200, h=100)
        self.lb = HitBox()

    def setposBol(self, posX, posY, radio):
        """Registra a posicao da bolinha. Deteccoes vazias (raio <= 0) sao ignoradas."""
        if radio is None or radio <= 0:
            return False
        # Converte para int nativo: valores uint16 do OpenCV/NumPy causam
        # OverflowError em subtracoes negativas no NumPy 2.x
        self.radio = int(radio)
        self.bx.insert(0, int(posX))
        self.by.insert(0, int(posY))
        del self.bx[self.historico:]
        del self.by[self.historico:]
        return True

    def clearHistory(self):
        self.bx.clear()
        self.by.clear()

    def getLastPos(self):
        if not self.bx:
            return None
        return self.bx[0], self.by[0]

    def setposFlip(self, posX, posY):
        if posX is None or posY is None:
            return
        self.hb.x = int(posX)
        self.hb.y = int(posY)
        self.hb.valid = True

    def setposLancador(self, x, y, w, h):
        if x is None:
            return
        self.lb.x, self.lb.y, self.lb.w, self.lb.h = int(x), int(y), int(w), int(h)
        self.lb.valid = True

    def getnextPos(self, mult):
        """Extrapola linearmente a proxima posicao. Retorna None sem historico suficiente."""
        if len(self.bx) < 2:
            return None
        valx = self.bx[0] - self.bx[1]
        valy = self.by[0] - self.by[1]
        return self.bx[0] + valx * mult, self.by[0] + valy * mult

    def _podeDisparar(self, atuador, cooldown):
        agora = time.monotonic()
        if agora - self._ultimoDisparo.get(atuador, float("-inf")) < cooldown:
            return False
        self._ultimoDisparo[atuador] = agora
        return True

    def isHit(self):
        """Retorna (True, lado) quando a posicao prevista esta na hitbox dos batedores.

        lado: 0 = esquerdo, 1 = direito. Respeita o cooldown por batedor, evitando
        enviar o mesmo comando a cada quadro.
        """
        pos = self.getnextPos(1)
        if pos is None or not self.hb.valid:
            return False, self.NENHUM
        xB, yB = pos
        hb = self.hb
        if not (hb.y < yB < hb.y + hb.h):
            return False, self.NENHUM

        lado = self.NENHUM
        if hb.x < xB < hb.x + hb.w / 2:
            lado = self.DIREITO
        elif hb.x - hb.w / 2 < xB < hb.x:
            lado = self.ESQUERDO

        if lado != self.NENHUM and self._podeDisparar(lado, self.cooldown):
            return True, lado
        return False, self.NENHUM

    def isLaunch(self):
        """Retorna True quando a bolinha esta prevista na area do lancador."""
        pos = self.getnextPos(1)
        if pos is None or not self.lb.valid:
            return False
        xB, yB = pos
        lb = self.lb
        dentro = lb.x < xB < lb.x + lb.w and lb.y < yB < lb.y + lb.h
        return dentro and self._podeDisparar("lancador", self.cooldownLancador)
