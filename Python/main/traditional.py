import cv2
import numpy


def mascaraHSV(hsv, faixa):
    """Mascara para uma faixa HSV. Se h_min > h_max, a faixa de matiz da a volta (vermelho)."""
    baixo = [faixa["s_min"], faixa["v_min"]]
    alto = [faixa["s_max"], faixa["v_max"]]
    if faixa["h_min"] <= faixa["h_max"]:
        return cv2.inRange(hsv, numpy.array([faixa["h_min"]] + baixo), numpy.array([faixa["h_max"]] + alto))
    m1 = cv2.inRange(hsv, numpy.array([faixa["h_min"]] + baixo), numpy.array([179] + alto))
    m2 = cv2.inRange(hsv, numpy.array([0] + baixo), numpy.array([faixa["h_max"]] + alto))
    return cv2.bitwise_or(m1, m2)


class traditional:

    def __init__(self, cfg, kernel=None):
        self.cfg = cfg
        self.kernel = kernel if kernel is not None else numpy.ones((5, 5), numpy.uint8)

    def mascara(self, image, nomeCor, hsv=None):
        if hsv is None:
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = mascaraHSV(hsv, self.cfg["cores"][nomeCor])
        # reduce the noise
        return cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)

    def _boundingRectCor(self, image, nomeCor, hsv=None):
        x, y, w, h = cv2.boundingRect(self.mascara(image, nomeCor, hsv))
        if w == 0 or h == 0:
            return None
        return x, y, w, h

    def findBase(self, image, hsv=None):
        """Localiza a marcacao entre os batedores (imagem).

        Retorna (x_centro, y_topo) ou (None, None) quando a marcacao nao e encontrada.
        """
        rect = self._boundingRectCor(image, "base", hsv)
        if rect is None:
            return None, None
        x, y, w, h = rect
        return int(x + w / 2), int(y)

    def findLancador(self, image, hsv=None):
        """Localiza a marcacao do lancador. Retorna (x, y, w, h) na imagem ou None."""
        rect = self._boundingRectCor(image, "lancador", hsv)
        if rect is None:
            return None
        x, y, w, h = rect
        dx, dy, dw, dh = self.cfg["lancador"]["ajuste"]
        return x + dx, y + dy, w + dw, h + dh

    def detectCircle(self, image, centro=None):
        """Detecta a bolinha. Retorna (x, y, r) como int, ou (0, 0, 0) se nada for encontrado.

        centro: posicao prevista (x, y) na imagem. Quando informado, procura primeiro
        numa regiao de interesse em volta dele (bem mais rapido) e so varre a imagem
        inteira se nao encontrar nada ali.
        """
        if centro is not None:
            margem = int(self.cfg["bolinha"]["roi_margem"])
            altura, largura = image.shape[:2]
            cx, cy = int(centro[0]), int(centro[1])
            x0, y0 = max(0, cx - margem), max(0, cy - margem)
            x1, y1 = min(largura, cx + margem), min(altura, cy + margem)
            if x1 - x0 > 2 * self.cfg["bolinha"]["raio_max"] and y1 - y0 > 2 * self.cfg["bolinha"]["raio_max"]:
                x, y, r = self._hough(image[y0:y1, x0:x1])
                if r > 0:
                    return x + x0, y + y0, r
        return self._hough(image)

    def _hough(self, image):
        b = self.cfg["bolinha"]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray_blurred = cv2.blur(gray, (3, 3))
        detected_circles = cv2.HoughCircles(gray_blurred,
                                            cv2.HOUGH_GRADIENT, 1, 20,
                                            param1=max(1, b["param1"]), param2=max(1, b["param2"]),
                                            minRadius=b["raio_min"], maxRadius=b["raio_max"])
        if detected_circles is None:
            return 0, 0, 0
        a, bb, r = numpy.around(detected_circles[0, 0]).astype(int)
        return int(a), int(bb), int(r)
