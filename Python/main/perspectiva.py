import cv2
import numpy


class Perspectiva:
    """Converte pontos entre a imagem da camera e as coordenadas da mesa.

    Com a perspectiva ativa, os 4 cantos da mesa marcados na calibracao sao mapeados
    para um retangulo de largura_mesa x altura_mesa. Assim a area dos batedores e as
    velocidades nao dependem da posicao/inclinacao da camera. Desativada, e a identidade.
    """

    def __init__(self, cfgPerspectiva):
        cantos = cfgPerspectiva.get("cantos") or []
        self.ativa = bool(cfgPerspectiva.get("ativa")) and len(cantos) == 4
        self.H = None
        self.Hinv = None
        if self.ativa:
            w = cfgPerspectiva["largura_mesa"]
            h = cfgPerspectiva["altura_mesa"]
            origem = numpy.float32(cantos)
            destino = numpy.float32([[0, 0], [w, 0], [w, h], [0, h]])
            self.H = cv2.getPerspectiveTransform(origem, destino)
            self.Hinv = cv2.getPerspectiveTransform(destino, origem)

    @staticmethod
    def _aplicar(M, pontos):
        pts = numpy.float32(pontos).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, M).reshape(-1, 2)

    def paraMesa(self, pontos):
        """Pontos da imagem -> mesa. Recebe/retorna uma lista de (x, y)."""
        if not self.ativa:
            return numpy.float32(pontos).reshape(-1, 2)
        return self._aplicar(self.H, pontos)

    def paraImagem(self, pontos):
        """Pontos da mesa -> imagem, para desenhar sobre o video."""
        if not self.ativa:
            return numpy.float32(pontos).reshape(-1, 2)
        return self._aplicar(self.Hinv, pontos)

    def pontoMesa(self, x, y):
        px, py = self.paraMesa([(x, y)])[0]
        return float(px), float(py)
