import sys

import cv2


def _valorExposicaoAuto(auto):
    # O significado de CAP_PROP_AUTO_EXPOSURE varia com o backend:
    # DirectShow (Windows) usa 0.75 = automatico e 0.25 = manual;
    # V4L2 (Linux/Raspberry) usa 3 = automatico e 1 = manual.
    if sys.platform.startswith("win"):
        return 0.75 if auto else 0.25
    return 3 if auto else 1


def aplicarAjustes(captura, cfgCamera):
    """Aplica exposicao e balanco de branco. Nem toda camera/driver aceita todos os ajustes."""
    captura.set(cv2.CAP_PROP_AUTO_EXPOSURE, _valorExposicaoAuto(cfgCamera["exposicao_auto"]))
    if not cfgCamera["exposicao_auto"]:
        captura.set(cv2.CAP_PROP_EXPOSURE, cfgCamera["exposicao"])
    captura.set(cv2.CAP_PROP_AUTO_WB, 1 if cfgCamera["balanco_branco_auto"] else 0)
    if not cfgCamera["balanco_branco_auto"]:
        captura.set(cv2.CAP_PROP_WB_TEMPERATURE, cfgCamera["temperatura_branco"])


def abrirCamera(indice, cfgCamera):
    captura = cv2.VideoCapture(indice)
    if not captura.isOpened():
        raise SystemExit("Nao foi possivel abrir a camera %d" % indice)
    aplicarAjustes(captura, cfgCamera)
    return captura


def lerQuadro(captura, cfgCamera):
    ret, frame = captura.read()
    if not ret or frame is None:
        return None
    return cv2.resize(frame, (cfgCamera["largura"], cfgCamera["altura"]))
