"""Ciclo de controle de uma mesa: marcacoes, deteccao, rastreamento e decisao de disparo.

Usado pelo main.py (PC), pelo pi_agente.py (Raspberry Pi) e pelo cliente de IA remoto.
"""
import cv2

from arduino import CMD_DIREITO, CMD_ESQUERDO, CMD_LANCAR
from desenho import desenhar, retanguloMesa
from mesa import mesa
from perspectiva import Perspectiva
from rastreador import Rastreador
from traditional import traditional


class ControleMesa:
    def __init__(self, cfg, lancador=False):
        self.cfg = cfg
        self.persp = Perspectiva(cfg["perspectiva"])
        self.m = mesa(cfg)
        self.rast = Rastreador(cfg["previsao"])
        self.trad = traditional(cfg)
        self.lancador = lancador
        # As marcacoes nao se movem: procura-las a cada N quadros economiza CPU (importante no Pi)
        self.intervaloMarcas = max(1, int(cfg["batedores"].get("intervalo_quadros", 1)))
        self.quadro = 0

    def atualizarMarcas(self, image):
        if self.quadro % self.intervaloMarcas == 0 or not self.m.hb.valid:
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            bx, by = self.trad.findBase(image, hsv)
            if bx is not None:
                self.m.setposFlip(*self.persp.pontoMesa(bx, by))
            if self.lancador:
                lanc = self.trad.findLancador(image, hsv)
                if lanc is not None:
                    self.m.setposLancador(*retanguloMesa(self.persp, *lanc))
        self.quadro += 1

    def detectarMath(self, image, agora):
        # Procura primeiro em volta da posicao prevista para este quadro
        centro = None
        if self.rast.valido:
            centro = self.persp.paraImagem([self.rast.preverEm(agora - self.rast.t)])[0]
        return self.trad.detectCircle(image, centro)

    def processar(self, image, agora, deteccao=None, permitirDisparo=True):
        """Processa um quadro capturado no instante `agora` e retorna os comandos a enviar.

        deteccao: (x, y, r) na imagem vinda de outro detector (IA); None usa o modo Math.
        permitirDisparo: False quando o Arduino esta no modo manual (nao gasta o cooldown).
        """
        self.atualizarMarcas(image)
        x, y, r = deteccao if deteccao is not None else self.detectarMath(image, agora)
        self.rast.atualizar(self.persp.pontoMesa(x, y) if r > 0 else None, agora)

        if not permitirDisparo:
            return []
        hit, lado = self.m.isHit(self.rast, agora)
        if hit:
            return [CMD_DIREITO if lado == mesa.DIREITO else CMD_ESQUERDO]
        if self.lancador and self.m.isLaunch(self.rast, agora):
            return [CMD_LANCAR]
        return []

    def desenhar(self, image, modo, fpsTxt):
        desenhar(image, self.persp, self.m, self.rast, modo, fpsTxt)

    def reiniciar(self):
        self.rast.reiniciar()
