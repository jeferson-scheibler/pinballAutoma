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
    """Aplica formato, exposicao e balanco de branco. Nem toda camera/driver aceita todos os ajustes."""
    if cfgCamera.get("fourcc"):
        captura.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*cfgCamera["fourcc"]))
    if cfgCamera.get("fps"):
        captura.set(cv2.CAP_PROP_FPS, cfgCamera["fps"])
    captura.set(cv2.CAP_PROP_AUTO_EXPOSURE, _valorExposicaoAuto(cfgCamera["exposicao_auto"]))
    if not cfgCamera["exposicao_auto"]:
        captura.set(cv2.CAP_PROP_EXPOSURE, cfgCamera["exposicao"])
    captura.set(cv2.CAP_PROP_AUTO_WB, 1 if cfgCamera["balanco_branco_auto"] else 0)
    if not cfgCamera["balanco_branco_auto"]:
        captura.set(cv2.CAP_PROP_WB_TEMPERATURE, cfgCamera["temperatura_branco"])


def abrirCamera(indice, cfgCamera, sairSeFalhar=True):
    """indice: numero da camera ou caminho do dispositivo (ex.: /dev/v4l/by-id/... no Linux,
    que nao muda de nome entre reinicios como /dev/video0)."""
    if sys.platform.startswith("linux"):
        captura = cv2.VideoCapture(indice, cv2.CAP_V4L2)
    else:
        captura = cv2.VideoCapture(indice)
    if not captura.isOpened():
        if sairSeFalhar:
            raise SystemExit("Nao foi possivel abrir a camera %s" % indice)
        return None
    aplicarAjustes(captura, cfgCamera)
    return captura


def lerQuadro(captura, cfgCamera):
    ret, frame = captura.read()
    if not ret or frame is None:
        return None
    return cv2.resize(frame, (cfgCamera["largura"], cfgCamera["altura"]))
