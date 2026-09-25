import time


class HitBox:
    """Retangulo em coordenadas da mesa. (x, y) e o ponto central superior da caixa."""

    def __init__(self, w=0, h=0):
        self.x = 0.0
        self.y = 0.0
        self.w = w
        self.h = h
        self.valid = False

    def contem(self, px, py):
        return (self.x - self.w / 2 < px < self.x + self.w / 2
                and self.y < py < self.y + self.h)

    def cantos(self):
        esq, dir_ = self.x - self.w / 2, self.x + self.w / 2
        return [(esq, self.y), (dir_, self.y), (dir_, self.y + self.h), (esq, self.y + self.h)]


class Retangulo:
    def __init__(self):
        self.x = self.y = self.w = self.h = 0.0
        self.valid = False

    def contem(self, px, py):
        return self.x < px < self.x + self.w and self.y < py < self.y + self.h

    def cantos(self):
        return [(self.x, self.y), (self.x + self.w, self.y),
                (self.x + self.w, self.y + self.h), (self.x, self.y + self.h)]


class mesa:
    # Lados retornados por isHit()
    ESQUERDO = 0
    DIREITO = 1
    NENHUM = 99

    PASSOS_TRAJETORIA = 12  # amostras da trajetoria prevista dentro da janela de latencia

    def __init__(self, cfg):
        bat = cfg["batedores"]
        prev = cfg["previsao"]
        self.hb = HitBox(w=bat["largura"], h=bat["altura"])
        self.suavizacaoBase = float(bat["suavizacao_base"])
        self.lb = Retangulo()
        self.velLancadorMax = float(cfg["lancador"]["velocidade_max"])
        self.latencia = prev["latencia_ms"] / 1000.0
        self.cooldown = prev["cooldown_ms"] / 1000.0
        self.cooldownLancador = prev["cooldown_lancador_ms"] / 1000.0
        self._ultimoDisparo = {}

    def setposFlip(self, posX, posY):
        """Atualiza a base dos batedores (coordenadas da mesa) com media movel exponencial."""
        if posX is None or posY is None:
            return
        if not self.hb.valid:
            self.hb.x, self.hb.y = posX, posY
            self.hb.valid = True
            return
        a = self.suavizacaoBase
        self.hb.x += a * (posX - self.hb.x)
        self.hb.y += a * (posY - self.hb.y)

    def setposLancador(self, x, y, w, h):
        self.lb.x, self.lb.y, self.lb.w, self.lb.h = x, y, w, h
        self.lb.valid = True

    def _podeDisparar(self, atuador, cooldown, agora):
        if agora - self._ultimoDisparo.get(atuador, float("-inf")) < cooldown:
            return False
        self._ultimoDisparo[atuador] = agora
        return True

    def trajetoria(self, rastreador):
        """Pontos previstos da bolinha entre agora e agora + latencia."""
        n = self.PASSOS_TRAJETORIA
        return [rastreador.preverEm(self.latencia * i / n) for i in range(n + 1)]

    def isHit(self, rastreador, agora=None):
        """Decide se um batedor deve ser acionado neste quadro.

        O comando leva `latencia` segundos para mover o braco. Por isso o disparo acontece
        quando a trajetoria prevista entra na area dos batedores dentro dessa janela,
        e nao apenas quando a bolinha ja esta la. O lado e definido pelo ponto de entrada.

        Retorna (True, lado) com lado 0 = esquerdo, 1 = direito; senao (False, 99).
        """
        agora = time.monotonic() if agora is None else agora
        if not rastreador.valido or not self.hb.valid:
            return False, self.NENHUM

        for px, py in self.trajetoria(rastreador):
            if self.hb.contem(px, py):
                lado = self.DIREITO if px > self.hb.x else self.ESQUERDO
                if self._podeDisparar(lado, self.cooldown, agora):
                    return True, lado
                return False, self.NENHUM
        return False, self.NENHUM

    def isLaunch(self, rastreador, agora=None):
        """True quando a bolinha esta (quase) parada na area do lancador."""
        agora = time.monotonic() if agora is None else agora
        if not rastreador.valido or not self.lb.valid:
            return False
        px, py = rastreador.posicao
        vx, vy = rastreador.velocidade
        parada = (vx * vx + vy * vy) ** 0.5 <= self.velLancadorMax
        return (self.lb.contem(px, py) and parada
                and self._podeDisparar("lancador", self.cooldownLancador, agora))
