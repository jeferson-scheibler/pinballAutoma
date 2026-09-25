import cv2
import numpy


class traditional:

    def __init__(self, kernel=None):
        self.kernel = kernel if kernel is not None else numpy.ones((5, 5), numpy.uint8)
        print("Método matemático iniciado")

    def _boundingRectCor(self, image, rangomin, rangomax):
        mask = cv2.inRange(image, numpy.array(rangomin), numpy.array(rangomax))
        # reduce the noise
        opening = cv2.morphologyEx(mask, cv2.MORPH_OPEN, self.kernel)
        x, y, w, h = cv2.boundingRect(opening)
        if w == 0 or h == 0:
            return None
        return x, y, w, h

    def findBase(self, image):
        """Localiza a marcacao vermelha entre os batedores.

        Retorna (x_centro, y_topo) ou (None, None) quando a marcacao nao e encontrada.
        """
        rect = self._boundingRectCor(image, [0, 0, 100], [60, 60, 255])  # B, G, R
        if rect is None:
            return None, None
        x, y, w, h = rect
        return int(x + w / 2), int(y)

    def findLancador(self, image):
        """Localiza a marcacao azul do lancador. Retorna (x, y, w, h) ou None."""
        rect = self._boundingRectCor(image, [60, 0, 0], [255, 60, 60])  # B, G, R
        if rect is None:
            return None
        x, y, w, h = rect
        return x + 15, y, w + 40, h + 30

    def detectCircle(self, image):
        """Detecta a bolinha. Retorna (x, y, r) como int, ou (0, 0, 0) se nada for encontrado."""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray_blurred = cv2.blur(gray, (3, 3))
        detected_circles = cv2.HoughCircles(gray_blurred,
                                            cv2.HOUGH_GRADIENT, 1, 20, param1=100,
                                            param2=30, minRadius=10, maxRadius=20)
        if detected_circles is None:
            return 0, 0, 0
        a, b, r = numpy.around(detected_circles[0, 0]).astype(int)
        return int(a), int(b), int(r)
