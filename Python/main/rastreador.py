import numpy


class Rastreador:
    """Filtro de Kalman de velocidade constante para a bolinha.

    Estado: [x, y, vx, vy] em unidades da mesa e unidades/segundo. Usa o tempo real
    entre quadros (dt), entao a previsao nao depende do FPS da camera. Quadros sem
    deteccao apenas avancam a previsao; apos varios quadros perdidos o rastreamento
    e descartado.
    """

    MEDICOES_MIN = 3  # medicoes necessarias antes de confiar na velocidade

    def __init__(self, cfgPrevisao):
        self.sigmaA = float(cfgPrevisao["aceleracao_desvio"])
        self.sigmaM = float(cfgPrevisao["medicao_desvio"])
        self.saltoMax = float(cfgPrevisao["salto_max"])
        self.perdidosMax = int(cfgPrevisao["quadros_perdidos_max"])
        self.Hm = numpy.array([[1.0, 0, 0, 0], [0, 1.0, 0, 0]])
        self.R = numpy.eye(2) * self.sigmaM ** 2
        self.reiniciar()

    def reiniciar(self):
        self.x = None
        self.P = None
        self.t = None
        self.medicoes = 0
        self.perdidos = 0
        self.trilha = []

    @property
    def valido(self):
        return self.x is not None and self.medicoes >= self.MEDICOES_MIN

    @property
    def posicao(self):
        return (float(self.x[0]), float(self.x[1])) if self.x is not None else None

    @property
    def velocidade(self):
        return (float(self.x[2]), float(self.x[3])) if self.x is not None else None

    def _iniciar(self, medida, t):
        self.x = numpy.array([medida[0], medida[1], 0.0, 0.0])
        # Velocidade inicial desconhecida: variancia alta
        self.P = numpy.diag([self.sigmaM ** 2, self.sigmaM ** 2, 1e6, 1e6])
        self.t = t
        self.medicoes = 1
        self.perdidos = 0
        self.trilha = [medida]

    def _prever(self, dt):
        F = numpy.array([[1.0, 0, dt, 0],
                         [0, 1.0, 0, dt],
                         [0, 0, 1.0, 0],
                         [0, 0, 0, 1.0]])
        # Ruido de aceleracao branca
        dt2, dt3, dt4 = dt * dt, dt ** 3, dt ** 4
        Q = self.sigmaA ** 2 * numpy.array([[dt4 / 4, 0, dt3 / 2, 0],
                                            [0, dt4 / 4, 0, dt3 / 2],
                                            [dt3 / 2, 0, dt2, 0],
                                            [0, dt3 / 2, 0, dt2]])
        self.x = F @ self.x
        self.P = F @ self.P @ F.T + Q

    def atualizar(self, medida, t):
        """Processa um quadro.

        medida: (x, y) em unidades da mesa, ou None se a bolinha nao foi detectada.
        t: instante da captura em segundos (time.monotonic()).
        """
        if self.x is None:
            if medida is not None:
                self._iniciar(medida, t)
            return

        dt = t - self.t
        self.t = t
        if dt > 0:
            self._prever(dt)

        if medida is None:
            self.perdidos += 1
            if self.perdidos > self.perdidosMax:
                self.reiniciar()
            return

        z = numpy.array(medida, dtype=float)
        inovacao = z - self.Hm @ self.x
        if numpy.hypot(*inovacao) > self.saltoMax:
            # Deteccao incompativel com a trajetoria (outra bolinha ou falso positivo)
            self._iniciar(medida, t)
            return

        S = self.Hm @ self.P @ self.Hm.T + self.R
        K = self.P @ self.Hm.T @ numpy.linalg.inv(S)
        self.x = self.x + K @ inovacao
        self.P = (numpy.eye(4) - K @ self.Hm) @ self.P
        self.medicoes += 1
        self.perdidos = 0
        self.trilha.insert(0, (float(z[0]), float(z[1])))
        del self.trilha[10:]

    def preverEm(self, dt):
        """Posicao prevista daqui a dt segundos (velocidade constante)."""
        x, y = self.posicao
        vx, vy = self.velocidade
        return x + vx * dt, y + vy * dt
