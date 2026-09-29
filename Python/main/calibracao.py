"""Ferramenta de calibracao da mesa.

Ajusta cores (HSV), deteccao da bolinha, area dos batedores, latencia, camera e
perspectiva, e salva tudo no config.json usado pelo main.py.

Teclas:
  1  cor da base dos batedores      2  cor do lancador
  3  deteccao da bolinha            4  batedores e previsao
  5  camera (exposicao/balanco)
  p  marcar os 4 cantos da mesa (sup. esq., sup. dir., inf. dir., inf. esq.)
  c  ativar/desativar a perspectiva
  s  salvar                         Esc sair
"""
import argparse
import time

import cv2
import numpy

import config
from camera import abrirCamera, aplicarAjustes, lerQuadro
from desenho import desenhar, retanguloMesa
from mesa import mesa
from perspectiva import Perspectiva
from rastreador import Rastreador
from traditional import traditional

JANELA = "Calibracao"
JANELA_AJUSTES = "Ajustes"
JANELA_MASCARA = "Mascara"
JANELA_MESA = "Mesa (perspectiva)"

ORDEM_CANTOS = ["superior esquerdo", "superior direito", "inferior direito", "inferior esquerdo"]


def controlesCor(cfg, nome):
    faixa = cfg["cores"][nome]
    return [(chave.upper(), faixa, chave, 179 if chave.startswith("h") else 255, None, None)
            for chave in ["h_min", "h_max", "s_min", "s_max", "v_min", "v_max"]]


def controlesBolinha(cfg):
    b = cfg["bolinha"]
    return [("Raio min", b, "raio_min", 100, None, None),
            ("Raio max", b, "raio_max", 100, None, None),
            ("Param1 (Canny)", b, "param1", 300, None, None),
            ("Param2 (acumulador)", b, "param2", 100, None, None)]


def controlesPrevisao(cfg):
    bat, prev = cfg["batedores"], cfg["previsao"]
    return [("Largura batedores", bat, "largura", 800, None, None),
            ("Altura batedores", bat, "altura", 400, None, None),
            ("Latencia (ms)", prev, "latencia_ms", 300, None, None),
            ("Cooldown (ms)", prev, "cooldown_ms", 1000, None, None)]


def controlesCamera(cfg):
    cam = cfg["camera"]
    return [("Exposicao auto", cam, "exposicao_auto", 1, lambda v: bool(v), int),
            # Escala tipica do DirectShow: -13 (curta) a 0 (longa)
            ("Exposicao (+13)", cam, "exposicao", 13, lambda v: v - 13, lambda v: int(v) + 13),
            ("Balanco auto", cam, "balanco_branco_auto", 1, lambda v: bool(v), int),
            ("Temperatura (x100)", cam, "temperatura_branco", 80, lambda v: v * 100, lambda v: int(v) // 100)]


class Calibracao:
    def __init__(self, args):
        self.args = args
        self.cfg = config.carregar(args.config)
        self.captura = abrirCamera(args.camera, self.cfg["camera"])
        self.modo = "1"
        self.cantosNovos = None
        self.alterado = False
        self.recriarObjetos()
        cv2.namedWindow(JANELA)
        cv2.setMouseCallback(JANELA, self.clique)
        self.criarControles()

    def recriarObjetos(self):
        """Recria os objetos que leem a configuracao (apos qualquer ajuste)."""
        self.persp = Perspectiva(self.cfg["perspectiva"])
        hbAnterior = getattr(self, "m", None)
        self.m = mesa(self.cfg)
        if hbAnterior is not None and hbAnterior.hb.valid:
            self.m.hb.x, self.m.hb.y, self.m.hb.valid = hbAnterior.hb.x, hbAnterior.hb.y, True
        self.rast = Rastreador(self.cfg["previsao"])
        self.trad = traditional(self.cfg)

    def criarControles(self):
        try:
            cv2.destroyWindow(JANELA_AJUSTES)
        except cv2.error:
            pass
        cv2.namedWindow(JANELA_AJUSTES)
        controles = {
            "1": lambda: controlesCor(self.cfg, "base"),
            "2": lambda: controlesCor(self.cfg, "lancador"),
            "3": lambda: controlesBolinha(self.cfg),
            "4": lambda: controlesPrevisao(self.cfg),
            "5": lambda: controlesCamera(self.cfg),
        }[self.modo]()
        for rotulo, secao, chave, maximo, deTrackbar, paraTrackbar in controles:
            valor = paraTrackbar(secao[chave]) if paraTrackbar else int(secao[chave])
            cv2.createTrackbar(rotulo, JANELA_AJUSTES, max(0, min(maximo, valor)), maximo,
                               self._callback(secao, chave, deTrackbar))

    def _callback(self, secao, chave, conversao):
        def aoMudar(v):
            secao[chave] = conversao(v) if conversao else v
            self.alterado = True
            if self.modo == "5":
                aplicarAjustes(self.captura, self.cfg["camera"])
            else:
                self.recriarObjetos()
        return aoMudar

    def clique(self, evento, x, y, flags, param):
        if evento != cv2.EVENT_LBUTTONDOWN or self.cantosNovos is None:
            return
        self.cantosNovos.append([int(x), int(y)])
        if len(self.cantosNovos) == 4:
            self.cfg["perspectiva"]["cantos"] = self.cantosNovos
            self.cfg["perspectiva"]["ativa"] = True
            self.cantosNovos = None
            self.alterado = True
            self.recriarObjetos()
            print("Perspectiva definida e ativada.")

    def mascaraAtual(self, image, hsv):
        if self.modo in ("1", "2"):
            return self.trad.mascara(image, "base" if self.modo == "1" else "lancador", hsv)
        return None

    def instrucao(self):
        if self.cantosNovos is not None:
            return "Clique no canto %s da mesa" % ORDEM_CANTOS[len(self.cantosNovos)]
        nomes = {"1": "Cor da base", "2": "Cor do lancador", "3": "Bolinha",
                 "4": "Batedores/previsao", "5": "Camera"}
        persp = "on" if self.persp.ativa else "off"
        return "[%s] perspectiva: %s  |  1-5 modo  p cantos  c persp.  s salvar" % (nomes[self.modo], persp)

    def executar(self):
        while True:
            image = lerQuadro(self.captura, self.cfg["camera"])
            agora = time.monotonic()
            if image is None:
                print("Falha ao ler quadro da camera")
                break
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            bruta = image.copy()

            bx, by = self.trad.findBase(image, hsv)
            if bx is not None:
                self.m.setposFlip(*self.persp.pontoMesa(bx, by))
            lanc = self.trad.findLancador(image, hsv)
            if lanc is not None:
                self.m.setposLancador(*retanguloMesa(self.persp, *lanc))
            x, y, r = self.trad.detectCircle(image)
            self.rast.atualizar(self.persp.pontoMesa(x, y) if r > 0 else None, agora)
            if r > 0:
                cv2.circle(image, (x, y), r, (0, 255, 255), 2)

            desenhar(image, self.persp, self.m, self.rast, 0, "")
            for cx, cy in (self.cantosNovos or self.cfg["perspectiva"]["cantos"]):
                cv2.circle(image, (cx, cy), 5, (0, 165, 255), -1)
            cv2.putText(image, self.instrucao(), (5, image.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            cv2.imshow(JANELA, image)

            mascara = self.mascaraAtual(bruta, hsv)
            if mascara is not None:
                cv2.imshow(JANELA_MASCARA, mascara)
            else:
                self._fechar(JANELA_MASCARA)

            if self.persp.ativa:
                p = self.cfg["perspectiva"]
                cv2.imshow(JANELA_MESA, cv2.warpPerspective(bruta, self.persp.H,
                                                            (p["largura_mesa"], p["altura_mesa"])))
            else:
                self._fechar(JANELA_MESA)

            k = cv2.waitKey(1) & 0xff
            if chr(k) in "12345" and chr(k) != self.modo:
                self.modo = chr(k)
                self.criarControles()
            elif k == ord("p"):
                self.cantosNovos = []
            elif k == ord("c"):
                if len(self.cfg["perspectiva"]["cantos"]) == 4:
                    self.cfg["perspectiva"]["ativa"] = not self.cfg["perspectiva"]["ativa"]
                    self.alterado = True
                    self.recriarObjetos()
                else:
                    print("Marque os 4 cantos com 'p' antes de ativar a perspectiva.")
            elif k == ord("s"):
                config.salvar(self.cfg, self.args.config)
                self.alterado = False
                print("Configuracao salva em", self.args.config)
            elif k == 27:
                break

        if self.alterado:
            print("Aviso: alteracoes nao salvas foram descartadas (use 's' para salvar).")
        self.captura.release()
        cv2.destroyAllWindows()

    @staticmethod
    def _fechar(janela):
        try:
            if cv2.getWindowProperty(janela, cv2.WND_PROP_VISIBLE) >= 0:
                cv2.destroyWindow(janela)
        except cv2.error:
            pass


def main():
    p = argparse.ArgumentParser(description="Calibracao da mesa de pinball")
    p.add_argument("--config", default=config.CAMINHO_PADRAO)
    p.add_argument("--camera", type=int, default=0)
    Calibracao(p.parse_args()).executar()


if __name__ == "__main__":
    main()
