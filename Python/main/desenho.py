"""Sobreposicoes desenhadas no video (area dos batedores, trajetoria, placar)."""
import cv2
import numpy


def retanguloMesa(persp, x, y, w, h):
    """Converte um retangulo da imagem para o retangulo envolvente em coordenadas da mesa."""
    pts = persp.paraMesa([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    (x0, y0), (x1, y1) = pts.min(axis=0), pts.max(axis=0)
    return float(x0), float(y0), float(x1 - x0), float(y1 - y0)


def desenharPoligono(image, persp, cantosMesa, cor):
    pts = persp.paraImagem(cantosMesa).astype(numpy.int32)
    cv2.polylines(image, [pts], True, cor, 1)


def pontoImagem(persp, x, y):
    px, py = persp.paraImagem([(x, y)])[0]
    return int(px), int(py)


def desenharPlacar(image, arduino, agora):
    font = cv2.FONT_HERSHEY_SIMPLEX
    largura = image.shape[1]
    status = arduino.textoStatus(agora)
    corStatus = (0, 0, 255) if arduino.ativo and not arduino.conectado(agora) else (100, 255, 0)
    cv2.putText(image, status, (largura - 260, 30), font, 0.6, corStatus, 2, cv2.LINE_AA)
    if not arduino.ativo:
        return
    cv2.putText(image, "Placar: %d" % arduino.total, (largura - 260, 65), font, 0.9, (0, 255, 255), 2, cv2.LINE_AA)
    # Destaque rapido quando um sensor e atingido
    if arduino.ultimoImpacto and agora - arduino.ultimoImpacto[1] < 0.5:
        cv2.putText(image, "Sensor %d!" % arduino.ultimoImpacto[0], (largura - 260, 95),
                    font, 0.6, (0, 165, 255), 2, cv2.LINE_AA)


def desenhar(image, persp, m, rast, modo, fpsTxt):
    """modo: texto exibido no canto (ex.: 'Math', 'Ai') ou 0/1 por compatibilidade."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    if not isinstance(modo, str):
        modo = 'Ai' if modo == 1 else 'Math'

    if m.hb.valid:
        hb = m.hb
        desenharPoligono(image, persp, hb.cantos(), (0, 255, 0))
        desenharPoligono(image, persp, [(hb.x, hb.y), (hb.x, hb.y + hb.h)], (0, 255, 0))
    if m.lb.valid:
        desenharPoligono(image, persp, m.lb.cantos(), (255, 255, 0))

    for x, y in rast.trilha:
        cv2.circle(image, pontoImagem(persp, x, y), 1, (255, 0, 0), 2)

    if rast.valido:
        cv2.circle(image, pontoImagem(persp, *rast.posicao), 6, (0, 255, 0), 2)
        # Trajetoria prevista ate o instante em que o braco estaria em movimento
        traj = numpy.int32([pontoImagem(persp, x, y) for x, y in m.trajetoria(rast)])
        cv2.polylines(image, [traj], False, (255, 0, 255), 2)

    cv2.putText(image, modo, (0, 70), font, 1, (100, 255, 0), 2, cv2.LINE_AA)
    cv2.putText(image, fpsTxt, (0, 45), font, 2, (100, 255, 0), 2, cv2.LINE_AA)
