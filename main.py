# -*- coding: utf-8 -*-
"""
TURNO NOCTURNO EN EL DEPOSITO 8
Terror psicologico + supervivencia con raycasting pseudo-3D (estilo Wolfenstein 3D).

Requisitos:  pip install pygame
Ejecutar:    python turno_nocturno_deposito8.py

CONTROLES
  OFICINA:  1/2/3 = cambiar camara | R = reportar anomalia | F = verter bidon en el generador
            E = salir al deposito  | ESPACIO o CLIC = disparar (solo si la Sombra esta en la puerta)
  DEPOSITO: W/A/S/D = mover | RATON o FLECHAS = girar | CLIC o ESPACIO = disparar
            E (junto a la puerta verde) = volver a la oficina
  GENERAL:  ENTER = continuar | ESC = menu / salir

Todo el arte y el sonido se generan por codigo: no necesita archivos externos.
"""
import array
import math
import random
import sys
from collections import deque

import pygame

# ----------------------------------------------------------------------------
# CONSTANTES GENERALES
# ----------------------------------------------------------------------------
ANCHO, ALTO = 800, 600
FPS = 60
COLW = 4                      # ancho de cada columna del raycaster (look retro + rendimiento)
SEGUNDOS_POR_NOCHE = 240      # duracion real de una noche (12:00 AM -> 6:00 AM). Cambialo a gusto.
NOCHE_FINAL = 6
OBJETIVO_CAZA = 8             # anomalias a eliminar en la noche 6

# Mapa: '#' pared, 'C' contenedor, 'D' puerta de la oficina, '.' suelo
MAPA_TXT = [
    "####################",
    "#........#.........#",
    "#.CC.CC..#..CC.CC..#",
    "#.CC.CC.....CC.CC..#",
    "#........#.........#",
    "####.#####.####.####",
    "#..................#",
    "#.CCC..CC..CC..CCC.#",
    "#.CCC..CC..CC..CCC.#",
    "#..................#",
    "####.####..####.####",
    "#........#.........#",
    "#.CC.CC..#..CC.CC..#",
    "#.CC.CC.....CC.CC..#",
    "#........#.........#",
    "####.#####D####.####",
    "####################",
]
SPAWN = (10.5, 14.5)          # donde aparece el jugador al salir de la oficina
CELDA_PUERTA = (10, 14)       # celda frente a la puerta de la oficina

# Dificultad por noche (indice 0 = noche 1)
BALAS_INICIALES = [5, 4, 4, 3, 3, 0]
BALAS_EN_MAPA = [8, 7, 6, 5, 4, 0]
BIDONES_EN_MAPA = [6, 5, 4, 4, 3, 4]

CAMARAS = [
    {"nombre": "CAM 1 - SALA NORTE", "pos": (1.5, 1.5), "ang": math.radians(28)},
    {"nombre": "CAM 2 - PASILLO CENTRAL", "pos": (1.5, 6.5), "ang": 0.0},
    {"nombre": "CAM 3 - PUERTA OFICINA", "pos": (18.5, 14.5), "ang": math.pi},
]
PLANO = 0.66                                  # tamano del plano de camara (FOV ~66 grados)
MITAD_FOV = math.atan(PLANO)
COLORES_MURO = {1: (120, 120, 132), 2: (165, 80, 44), 3: (40, 175, 85)}

MON = pygame.Rect(118, 52, 564, 300)          # pantalla del monitor en la oficina


# ----------------------------------------------------------------------------
# MAPA Y RAYCASTING
# ----------------------------------------------------------------------------
class Mapa:
    """Rejilla del deposito + utilidades (rayos, visibilidad, busqueda de caminos)."""

    def __init__(self):
        eq = {"#": 1, "C": 2, "D": 3, ".": 0}
        self.celdas = [[eq[c] for c in fila] for fila in MAPA_TXT]
        self.alto = len(self.celdas)
        self.ancho = len(self.celdas[0])
        self.libres = [(x, y) for y in range(self.alto) for x in range(self.ancho)
                       if self.celdas[y][x] == 0]

    def solido(self, x, y):
        ix, iy = int(x // 1), int(y // 1)
        if ix < 0 or iy < 0 or ix >= self.ancho or iy >= self.alto:
            return True
        return self.celdas[iy][ix] != 0

    def lanzar_rayo(self, px, py, dx, dy, maxd=40.0):
        """DDA. Devuelve (distancia, lado, tipo_de_muro, fraccion_de_textura)."""
        mx, my = int(px), int(py)
        ddx = abs(1.0 / dx) if dx else 1e30
        ddy = abs(1.0 / dy) if dy else 1e30
        if dx < 0:
            sx, lx = -1, (px - mx) * ddx
        else:
            sx, lx = 1, (mx + 1.0 - px) * ddx
        if dy < 0:
            sy, ly = -1, (py - my) * ddy
        else:
            sy, ly = 1, (my + 1.0 - py) * ddy
        celdas, w, h = self.celdas, self.ancho, self.alto
        while True:
            if lx < ly:
                dist = lx
                lx += ddx
                mx += sx
                lado = 0
            else:
                dist = ly
                ly += ddy
                my += sy
                lado = 1
            if mx < 0 or my < 0 or mx >= w or my >= h:
                return (maxd, lado, 1, 0.0)
            t = celdas[my][mx]
            if t:
                wx = (py + dist * dy) if lado == 0 else (px + dist * dx)
                return (dist, lado, t, wx - math.floor(wx))
            if dist > maxd:
                return (maxd, lado, 0, 0.0)

    def visible_desde(self, px, py, ang, mitad_fov, x, y, alcance=30.0):
        """True si el punto (x,y) esta dentro del cono de vision y sin muros en medio."""
        dx, dy = x - px, y - py
        d = math.hypot(dx, dy)
        if d > alcance:
            return False
        if d < 0.01:
            return True
        da = (math.atan2(dy, dx) - ang + math.pi) % (2 * math.pi) - math.pi
        if abs(da) > mitad_fov:
            return False
        return self.lanzar_rayo(px, py, dx / d, dy / d)[0] > d - 0.2

    def linea_libre(self, x0, y0, x1, y1):
        """True si no hay muros entre dos puntos."""
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d < 0.01:
            return True
        return self.lanzar_rayo(x0, y0, dx / d, dy / d)[0] > d

    def camino_siguiente(self, origen, destino):
        """BFS desde el destino; devuelve la siguiente celda que acerca 'origen' a 'destino'."""
        if origen == destino:
            return None
        q = deque([destino])
        prev = {destino: None}
        while q:
            c = q.popleft()
            if c == origen:
                break
            for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (c[0] + ddx, c[1] + ddy)
                if n in prev:
                    continue
                if 0 <= n[0] < self.ancho and 0 <= n[1] < self.alto and self.celdas[n[1]][n[0]] == 0:
                    prev[n] = c
                    q.append(n)
        return prev.get(origen)


# ----------------------------------------------------------------------------
# SONIDO PROCEDURAL (sin archivos). Si no hay audio, el juego sigue en silencio.
# ----------------------------------------------------------------------------
class Sonido:
    def __init__(self):
        self.ok = False
        self.sonidos = {}
        self.zumbando = False
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init(22050, -16, 1, 512)
            info = pygame.mixer.get_init()
            if info and info[1] == -16:
                self.rate, _, self.canales = info
                self.ok = True
        except pygame.error:
            self.ok = False
        if self.ok:
            try:
                self._crear()
            except Exception:
                self.ok = False

    def _hacer(self, dur, f):
        n = int(self.rate * dur)
        buf = array.array("h")
        for i in range(n):
            v = max(-1.0, min(1.0, f(i / self.rate, i / n)))
            s = int(v * 30000)
            for _ in range(self.canales):
                buf.append(s)
        return pygame.mixer.Sound(buffer=buf.tobytes())

    def _crear(self):
        tau = 2 * math.pi
        rnd = random.uniform
        self.sonidos["disparo"] = self._hacer(
            0.45, lambda t, k: rnd(-1, 1) * (1 - k) ** 3 * 0.9 + math.sin(tau * 70 * t) * (1 - k) ** 2 * 0.7)
        self.sonidos["click"] = self._hacer(
            0.06, lambda t, k: 0.35 * (1 if math.sin(tau * 900 * t) > 0 else -1) * (1 - k))
        self.sonidos["recoger"] = self._hacer(
            0.2, lambda t, k: 0.4 * math.sin(tau * (880 if k < 0.5 else 1320) * t) * (1 - k))
        self.sonidos["alerta"] = self._hacer(
            0.6, lambda t, k: 0.35 * math.sin(tau * 110 * t) * math.sin(tau * 6 * t) * (1 - k))
        self.sonidos["susto"] = self._hacer(
            1.4, lambda t, k: rnd(-1, 1) * 0.8 * (1 - k * 0.5) + 0.3 * (((t * 90) % 1) * 2 - 1))
        # Zumbido del generador: 1 s exacto con frecuencias enteras => bucle sin clics
        self.sonidos["zumbido"] = self._hacer(
            1.0, lambda t, k: 0.22 * (math.sin(tau * 55 * t) + 0.5 * math.sin(tau * 110 * t)
                                      + 0.25 * math.sin(tau * 165 * t)))
        self.sonidos["zumbido"].set_volume(0.5)

    def tocar(self, nombre):
        if self.ok and nombre in self.sonidos:
            self.sonidos[nombre].play()

    def zumbido(self, encendido):
        if not self.ok:
            return
        if encendido and not self.zumbando:
            self.sonidos["zumbido"].play(-1)
            self.zumbando = True
        elif not encendido and self.zumbando:
            self.sonidos["zumbido"].stop()
            self.zumbando = False

    def parar(self):
        if self.ok:
            pygame.mixer.stop()
            self.zumbando = False


# ----------------------------------------------------------------------------
# SPRITES GENERADOS POR CODIGO
# ----------------------------------------------------------------------------
def crear_sprites():
    s = {}
    # Bidon de gasolina
    sf = pygame.Surface((64, 64), pygame.SRCALPHA)
    pygame.draw.rect(sf, (175, 32, 26), (14, 16, 36, 44), border_radius=4)
    pygame.draw.rect(sf, (110, 15, 15), (14, 16, 36, 44), 2, border_radius=4)
    pygame.draw.rect(sf, (235, 205, 45), (20, 30, 24, 12))
    pygame.draw.rect(sf, (60, 60, 60), (36, 8, 10, 10))
    pygame.draw.lines(sf, (40, 40, 40), False, [(18, 16), (18, 8), (32, 8), (32, 16)], 3)
    s["bidon"] = sf
    # Cartuchos de escopeta
    sf = pygame.Surface((64, 64), pygame.SRCALPHA)
    for ox in (12, 36):
        pygame.draw.rect(sf, (200, 40, 30), (ox, 22, 16, 30), border_radius=3)
        pygame.draw.rect(sf, (215, 175, 60), (ox, 46, 16, 10), border_radius=2)
    s["balas"] = sf
    # Anomalia (2 fotogramas para que parpadee)
    for k in range(2):
        sf = pygame.Surface((64, 64), pygame.SRCALPHA)
        pygame.draw.ellipse(sf, (40, 10, 60, 120), (4, 6, 56, 52))
        pygame.draw.ellipse(sf, (70, 20, 90, 170), (12, 14, 40, 36))
        for (ex, ey) in ((22, 26), (42, 26), (32, 38)):
            r = 5 + k * 2
            pygame.draw.circle(sf, (255, 40, 40), (ex, ey), r)
            pygame.draw.circle(sf, (255, 230, 230), (ex, ey), 2)
        s["anomalia%d" % k] = sf
    # La Sombra
    sf = pygame.Surface((64, 64), pygame.SRCALPHA)
    pygame.draw.polygon(sf, (8, 8, 10), [(32, 4), (40, 9), (42, 22), (50, 40), (46, 62),
                                         (18, 62), (14, 40), (22, 22), (24, 9)])
    pygame.draw.line(sf, (8, 8, 10), (22, 24), (4, 54), 5)
    pygame.draw.line(sf, (8, 8, 10), (42, 24), (60, 54), 5)
    pygame.draw.circle(sf, (120, 0, 0), (27, 15), 5)
    pygame.draw.circle(sf, (120, 0, 0), (37, 15), 5)
    pygame.draw.circle(sf, (255, 40, 30), (27, 15), 3)
    pygame.draw.circle(sf, (255, 40, 30), (37, 15), 3)
    s["sombra"] = sf
    return s


# ----------------------------------------------------------------------------
# ENTIDADES DEL JUEGO
# ----------------------------------------------------------------------------
class Jugador:
    """El guardia (Player): posicion, angulo, cordura, municion y bidones."""

    def __init__(self):
        self.reiniciar(1)

    def reiniciar(self, noche):
        self.x, self.y = SPAWN
        self.ang = -math.pi / 2
        self.cordura = 100.0
        self.balas = BALAS_INICIALES[noche - 1]
        self.bidones = 0
        self.enfriamiento = 0.0
        self.retroceso = 0.0
        self.caminando = False

    def _libre(self, mapa, x, y, r=0.25):
        return not any(mapa.solido(x + ox, y + oy) for ox in (-r, r) for oy in (-r, r))

    def mover(self, mapa, adelante, lateral, dt):
        vel = 3.0
        dx = (math.cos(self.ang) * adelante - math.sin(self.ang) * lateral) * vel * dt
        dy = (math.sin(self.ang) * adelante + math.cos(self.ang) * lateral) * vel * dt
        if self._libre(mapa, self.x + dx, self.y):
            self.x += dx
        if self._libre(mapa, self.x, self.y + dy):
            self.y += dy
        self.caminando = abs(adelante) + abs(lateral) > 0


class Generador:
    """El generador: consume gasolina sin parar. Sin gasolina => sin luz."""

    def __init__(self):
        self.nivel = 100.0
        self.noche = 1

    def reiniciar(self, noche):
        self.nivel = 100.0
        self.noche = noche

    @property
    def encendido(self):
        return self.nivel > 0

    def tasa(self):  # % por segundo
        return 0.20 + 0.055 * self.noche if self.noche < NOCHE_FINAL else 0.15

    def actualizar(self, dt):
        self.nivel = max(0.0, self.nivel - self.tasa() * dt)

    def rellenar(self, cantidad=35.0):
        self.nivel = min(100.0, self.nivel + cantidad)

    def fuga(self, cantidad=15.0):
        self.nivel = max(0.0, self.nivel - cantidad)


class Anomalia:
    """Anomalia ambiental: aparece en camaras/pasillos y erosiona la cordura si se ignora."""

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.fase = random.random() * 6.0
        self.edad = 0.0

    def actualizar(self, dt):
        self.edad += dt


class Objeto:
    """Bidon de gasolina o caja de cartuchos tirada por el mapa."""

    def __init__(self, x, y, tipo):
        self.x, self.y, self.tipo = x, y, tipo
        self.recogido = False


class Sombra:
    """La entidad activa: avanza hacia la puerta de la oficina o persigue al jugador."""

    def __init__(self):
        self.x = self.y = 0.0
        self.estado = "aturdida"   # aturdida (ausente) | acechando | puerta
        self.temporizador = 10.0
        self.t_puerta = 0.0
        self.memoria = 0.0         # tiempo restante de persecucion directa al jugador

    @property
    def presente(self):
        return self.estado != "aturdida"

    def reiniciar(self, noche, mapa):
        self.estado = "aturdida"
        self.temporizador = max(6.0, 24.0 - 3.0 * noche) if noche < NOCHE_FINAL else 6.0
        self.memoria = 0.0
        self.colocar_lejos(mapa)

    def colocar_lejos(self, mapa):
        cand = [c for c in mapa.libres
                if math.hypot(c[0] + 0.5 - SPAWN[0], c[1] + 0.5 - SPAWN[1]) >= 11]
        cx, cy = random.choice(cand)
        self.x, self.y = cx + 0.5, cy + 0.5

    def ahuyentar(self, noche, mapa):
        self.estado = "aturdida"
        self.temporizador = max(7.0, 15.0 - 1.5 * noche)
        self.memoria = 0.0
        self.colocar_lejos(mapa)

    def velocidad(self, gm):
        n = gm.noche
        base = 1.6 if n >= NOCHE_FINAL else 0.5 + 0.2 * n
        if self.memoria > 0:
            base = base * 1.5 + 0.3
        if not gm.gen.encendido:
            base *= 1.6            # sin luz las entidades atacan con mas fuerza
        return base

    def _mover(self, tx, ty, paso):
        dx, dy = tx - self.x, ty - self.y
        d = math.hypot(dx, dy)
        if d < 1e-4:
            return
        paso = min(paso, d)
        self.x += dx / d * paso
        self.y += dy / d * paso

    def actualizar(self, dt, gm):
        mapa, j = gm.mapa, gm.jugador
        if self.estado == "aturdida":
            self.temporizador -= dt
            if self.temporizador <= 0:
                self.estado = "acechando"
            return
        en_dep = gm.modo == "deposito"
        if en_dep:
            d = math.hypot(j.x - self.x, j.y - self.y)
            if d < 0.7:
                gm.matar("sombra")
                return
            visto = d < 9 and mapa.linea_libre(self.x, self.y, j.x, j.y)
            if visto or d < 2.5:
                self.memoria = 3.0
            else:
                self.memoria = max(0.0, self.memoria - dt)
        else:
            self.memoria = 0.0

        if self.estado == "puerta":
            if en_dep:
                if self.memoria > 0:
                    self.estado = "acechando"
                return
            self.t_puerta -= dt
            if self.t_puerta <= 0:
                gm.matar("puerta")
            return

        # Estado "acechando": camina hacia el jugador (si lo ve) o hacia la puerta
        if en_dep and self.memoria > 0:
            objetivo, dest = (j.x, j.y), (int(j.x), int(j.y))
        else:
            objetivo, dest = (CELDA_PUERTA[0] + 0.5, CELDA_PUERTA[1] + 0.5), CELDA_PUERTA
        sig = mapa.camino_siguiente((int(self.x), int(self.y)), dest)
        tx, ty = objetivo if sig is None else (sig[0] + 0.5, sig[1] + 0.5)
        self._mover(tx, ty, self.velocidad(gm) * dt)
        if self.memoria <= 0 and math.hypot(self.x - (CELDA_PUERTA[0] + 0.5),
                                            self.y - (CELDA_PUERTA[1] + 0.5)) < 0.45:
            self.estado = "puerta"
            self.t_puerta = max(2.5, 4.5 - 0.3 * gm.noche)
            gm.sonido.tocar("alerta")


# ----------------------------------------------------------------------------
# GAME MANAGER: bucle principal, estados, dibujo y reglas
# ----------------------------------------------------------------------------
class GameManager:
    def __init__(self):
        pygame.mixer.pre_init(22050, -16, 1, 512)
        pygame.init()
        pygame.display.set_caption("Turno Nocturno en el Deposito 8")
        self.pantalla = pygame.display.set_mode((ANCHO, ALTO))
        self.reloj = pygame.time.Clock()
        fam = "consolas,couriernew,monospace"
        self.f_peq = pygame.font.SysFont(fam, 16, bold=True)
        self.f_med = pygame.font.SysFont(fam, 22, bold=True)
        self.f_gra = pygame.font.SysFont(fam, 44, bold=True)
        self.f_tit = pygame.font.SysFont(fam, 60, bold=True)

        self.mapa = Mapa()
        self.sonido = Sonido()
        self.imgs = crear_sprites()
        self.jugador = Jugador()
        self.gen = Generador()
        self.sombra = Sombra()
        self.anomalias = []
        self.objetos = []
        self.mensajes = []          # [texto, tiempo_restante]
        self.t_global = 0.0
        self.t_bob = 0.0
        self.estado = "menu"        # menu | intro | juego | susto | gameover | noche_superada | victoria
        self.modo = "oficina"       # oficina | deposito
        self.noche = 1
        self.tiempo = 0.0
        self.cam = 0
        self.eliminadas = 0
        self.t_estado = 0.0
        self.causa = ""
        self.flash = 0.0
        self.alucina = 0.0
        self.alucina_pos = (0, 0)
        self.cero_cordura = 0.0
        self.t_anomalia = 8.0
        self.fuga_hecha = False
        self.aviso_gas = False
        self.running = True
        self.botones = [pygame.Rect(130 + i * 125, 366, 115, 32) for i in range(3)]
        self.boton_reportar = pygame.Rect(530, 366, 150, 32)
        self._preparar_efectos()

    # ------------------------------------------------------------------ efectos
    def _preparar_efectos(self):
        """Pre-genera ruido, scanlines y vineta para no gastar CPU cada fotograma."""
        self.ruido_cam = []
        self.ruido_full = []
        for _ in range(4):
            for (w, h, dest, lista) in ((141, 75, (MON.w, MON.h), self.ruido_cam),
                                         (200, 150, (ANCHO, ALTO), self.ruido_full)):
                sf = pygame.Surface((w, h))
                for y in range(h):
                    for x in range(w):
                        v = random.randint(0, 255)
                        sf.set_at((x, y), (v, v, v))
                lista.append(pygame.transform.scale(sf, dest))
        self.scan = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
        for y in range(0, ALTO, 3):
            pygame.draw.line(self.scan, (0, 0, 0, 70), (0, y), (ANCHO, y))
        self.vineta = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
        for i in range(80):
            a = int(210 * (1 - i / 80) ** 2)
            pygame.draw.rect(self.vineta, (0, 0, 0, a), (i, i, ANCHO - 2 * i, ALTO - 2 * i), 1)

    # ------------------------------------------------------------------ utilidades
    def texto(self, s, fuente, color, pos, centro=False):
        img = fuente.render(s, True, color)
        r = img.get_rect(center=pos) if centro else img.get_rect(topleft=pos)
        self.pantalla.blit(img, r)
        return r

    def msg(self, s, t=3.0):
        self.mensajes.append([s, t])
        self.mensajes = self.mensajes[-3:]

    def _modo_raton(self, capturar):
        pygame.event.set_grab(capturar)
        pygame.mouse.set_visible(not capturar)
        pygame.mouse.get_rel()

    def hora_texto(self):
        minutos = int(self.tiempo / SEGUNDOS_POR_NOCHE * 360)
        h = (minutos // 60) % 12
        return "%d:%02d AM" % (h if h else 12, minutos % 60)

    # ------------------------------------------------------------------ flujo de noches
    def iniciar_noche(self, n):
        self.noche = n
        self.tiempo = 0.0
        self.jugador.reiniciar(n)
        self.gen.reiniciar(n)
        self.modo = "oficina"
        self.cam = 0
        self.anomalias = []
        self.objetos = []
        self.mensajes = []
        self.eliminadas = 0
        self.flash = 0.0
        self.cero_cordura = 0.0
        self.t_anomalia = 8.0 if n < NOCHE_FINAL else 3.0
        self.fuga_hecha = False
        self.aviso_gas = False
        self.sombra.reiniciar(n, self.mapa)
        libres = [c for c in self.mapa.libres
                  if math.hypot(c[0] + 0.5 - SPAWN[0], c[1] + 0.5 - SPAWN[1]) > 3.0]
        random.shuffle(libres)
        for _ in range(BIDONES_EN_MAPA[n - 1]):
            x, y = libres.pop()
            self.objetos.append(Objeto(x + 0.5, y + 0.5, "bidon"))
        for _ in range(BALAS_EN_MAPA[n - 1]):
            x, y = libres.pop()
            self.objetos.append(Objeto(x + 0.5, y + 0.5, "balas"))
        self.sonido.parar()
        self._modo_raton(False)
        self.estado = "intro"
        self.t_estado = 3.5

    def terminar_noche(self):
        self.estado = "noche_superada"
        self.t_estado = 0.0
        self.sonido.parar()
        self.sonido.tocar("recoger")
        self._modo_raton(False)
        self.modo = "oficina"

    def matar(self, causa):
        if self.estado != "juego":
            return
        self.estado = "susto"
        self.t_estado = 1.6
        self.causa = causa
        self.sonido.parar()
        self.sonido.tocar("susto")
        self._modo_raton(False)

    # ------------------------------------------------------------------ acciones del jugador
    def entrar_deposito(self):
        if self.modo == "deposito":
            return
        if self.sombra.estado == "puerta":
            self.msg("¡La Sombra esta en la puerta! ¡Dispara!", 2.0)
            return
        if self.sombra.presente and math.hypot(self.sombra.x - SPAWN[0], self.sombra.y - SPAWN[1]) < 2.5:
            self.msg("La Sombra esta demasiado cerca de la puerta...", 2.0)
            return
        self.modo = "deposito"
        j = self.jugador
        j.x, j.y = SPAWN
        j.ang = -math.pi / 2
        self._modo_raton(True)

    def entrar_oficina(self):
        if self.modo == "oficina":
            return
        if math.hypot(self.jugador.x - SPAWN[0], self.jugador.y - SPAWN[1]) > 1.8:
            self.msg("Acercate a la puerta verde para volver", 1.5)
            return
        self.modo = "oficina"
        self._modo_raton(False)
        if self.sombra.estado == "puerta":
            self.sombra.t_puerta = max(self.sombra.t_puerta, 3.0)

    def rellenar_generador(self):
        j = self.jugador
        if self.modo != "oficina":
            return
        if j.bidones <= 0:
            self.msg("No llevas bidones. Busca en el deposito.", 2.0)
        elif self.gen.nivel >= 99:
            self.msg("El generador ya esta lleno.", 2.0)
        else:
            j.bidones -= 1
            self.gen.rellenar(35)
            self.aviso_gas = False
            self.sonido.tocar("recoger")
            self.msg("Generador rellenado (+35%)", 2.0)

    def reportar(self):
        if self.modo != "oficina" or not self.gen.encendido:
            return
        if self.noche >= NOCHE_FINAL:
            self.msg("Modo caza: elimina las anomalias a tiros.", 2.0)
            return
        cam = CAMARAS[self.cam]
        for a in self.anomalias:
            if self.mapa.visible_desde(cam["pos"][0], cam["pos"][1], cam["ang"], MITAD_FOV, a.x, a.y, 24):
                self.anomalias.remove(a)
                self.jugador.cordura = min(100.0, self.jugador.cordura + 8)
                self.sonido.tocar("recoger")
                self.msg("Anomalia reportada. Cordura +8", 2.5)
                return
        self.msg("No ves nada raro en esta camara.", 1.8)

    def disparar(self):
        j = self.jugador
        if j.enfriamiento > 0 or self.estado != "juego":
            return
        infinito = self.noche >= NOCHE_FINAL
        if self.modo == "oficina":
            if self.sombra.estado != "puerta":
                self.msg("No hay nada que disparar.", 1.2)
                return
            if not infinito and j.balas <= 0:
                self.sonido.tocar("click")
                self.msg("¡Sin cartuchos!", 1.5)
                j.enfriamiento = 0.3
                return
            self._efecto_disparo(infinito)
            self.sombra.ahuyentar(self.noche, self.mapa)
            self.msg("La Sombra huye... por ahora.", 2.5)
            return
        if not infinito and j.balas <= 0:
            self.sonido.tocar("click")
            self.msg("¡Sin cartuchos!", 1.5)
            j.enfriamiento = 0.3
            return
        self._efecto_disparo(infinito)
        self._resolver_disparo_deposito()

    def _efecto_disparo(self, infinito):
        j = self.jugador
        if not infinito:
            j.balas -= 1
        j.enfriamiento = 0.9
        j.retroceso = 1.0
        self.flash = 0.18
        self.sonido.tocar("disparo")

    def _resolver_disparo_deposito(self):
        """Busca el objetivo mas cercano dentro de la mira (con linea de vision libre)."""
        j = self.jugador
        candidatos = []
        if self.sombra.presente:
            candidatos.append(("sombra", self.sombra))
        candidatos += [("anomalia", a) for a in self.anomalias]
        mejor = None
        for tipo, e in candidatos:
            dx, dy = e.x - j.x, e.y - j.y
            d = math.hypot(dx, dy)
            if d < 0.1:
                continue
            da = (math.atan2(dy, dx) - j.ang + math.pi) % (2 * math.pi) - math.pi
            tol = math.atan2(0.55, d) + 0.04      # perdigones: area generosa
            if abs(da) <= tol and self.mapa.linea_libre(j.x, j.y, e.x, e.y):
                if mejor is None or d < mejor[0]:
                    mejor = (d, tipo, e)
        if not mejor:
            return
        _, tipo, e = mejor
        if tipo == "sombra":
            self.sombra.ahuyentar(self.noche, self.mapa)
            self.msg("¡La Sombra se desvanece!", 2.5)
        else:
            self.anomalias.remove(e)
            self.eliminadas += 1
            j.cordura = min(100.0, j.cordura + 6)
            self.msg("Anomalia neutralizada", 2.0)

    # ------------------------------------------------------------------ eventos
    def procesar_eventos(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.KEYDOWN:
                self._tecla(ev.key)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.estado == "juego":
                if self.modo == "deposito":
                    self.disparar()
                else:
                    self._clic_oficina(ev.pos)
            elif ev.type == pygame.MOUSEMOTION and self.estado == "juego" and self.modo == "deposito":
                self.jugador.ang += ev.rel[0] * 0.0025

    def _clic_oficina(self, pos):
        for i, r in enumerate(self.botones):
            if r.collidepoint(pos):
                self.cam = i
                return
        if self.boton_reportar.collidepoint(pos):
            self.reportar()
            return
        self.disparar()

    def _tecla(self, k):
        if k == pygame.K_ESCAPE:
            if self.estado == "menu":
                self.running = False
            else:
                self.sonido.parar()
                self._modo_raton(False)
                self.estado = "menu"
            return
        if k == pygame.K_RETURN:
            if self.estado == "menu":
                self.iniciar_noche(1)
            elif self.estado == "gameover":
                self.iniciar_noche(self.noche)
            elif self.estado == "noche_superada" and self.t_estado > 1.0:
                self.iniciar_noche(self.noche + 1)
            elif self.estado == "victoria":
                self.estado = "menu"
            return
        if self.estado != "juego":
            return
        if k == pygame.K_e:
            self.entrar_deposito() if self.modo == "oficina" else self.entrar_oficina()
        elif k in (pygame.K_1, pygame.K_2, pygame.K_3) and self.modo == "oficina":
            self.cam = k - pygame.K_1
        elif k == pygame.K_r:
            self.reportar()
        elif k == pygame.K_f:
            self.rellenar_generador()
        elif k == pygame.K_SPACE:
            self.disparar()

    # ------------------------------------------------------------------ logica
    def actualizar(self, dt):
        self.t_global += dt
        for m in self.mensajes:
            m[1] -= dt
        self.mensajes = [m for m in self.mensajes if m[1] > 0]
        if self.estado in ("intro", "susto", "noche_superada"):
            self.t_estado += dt if self.estado == "noche_superada" else -dt
            if self.estado == "intro" and self.t_estado <= 0:
                self.estado = "juego"
                self.sonido.zumbido(True)
                if self.noche >= NOCHE_FINAL:
                    self.entrar_deposito()
            elif self.estado == "susto" and self.t_estado <= 0:
                self.estado = "gameover"
            return
        if self.estado == "juego":
            self._actualizar_juego(dt)

    def _actualizar_juego(self, dt):
        j, gen = self.jugador, self.gen
        en_dep = self.modo == "deposito"

        # Reloj de la noche (la noche 6 no tiene hora: es una caza)
        if self.noche < NOCHE_FINAL:
            self.tiempo += dt
            if self.tiempo >= SEGUNDOS_POR_NOCHE:
                self.terminar_noche()
                return
            # Cada 3 horas del juego (3:00 AM) el generador sufre una fuga
            if not self.fuga_hecha and self.tiempo >= SEGUNDOS_POR_NOCHE / 2:
                self.fuga_hecha = True
                gen.fuga(15)
                self.msg("3:00 AM - ¡Fuga en el generador! -15% de gasolina", 4.0)
                self.sonido.tocar("alerta")

        gen.actualizar(dt)
        self.sonido.zumbido(gen.encendido)
        if gen.nivel < 25 and not self.aviso_gas and gen.encendido:
            self.aviso_gas = True
            self.msg("¡Gasolina baja! Busca bidones en el deposito", 4.0)
        if gen.nivel >= 35:
            self.aviso_gas = False
        if not gen.encendido and self.t_global % 6 < dt:
            self.msg("SIN LUZ... las entidades se acercan", 3.0)

        # Recarga de armas / retroceso
        j.enfriamiento = max(0.0, j.enfriamiento - dt)
        j.retroceso = max(0.0, j.retroceso - dt * 2.2)
        self.flash = max(0.0, self.flash - dt)

        # Movimiento en el deposito
        if en_dep:
            k = pygame.key.get_pressed()
            adel = (1 if k[pygame.K_w] else 0) - (1 if k[pygame.K_s] else 0)
            lat = (1 if k[pygame.K_d] else 0) - (1 if k[pygame.K_a] else 0)
            if k[pygame.K_RIGHT]:
                j.ang += 2.2 * dt
            if k[pygame.K_LEFT]:
                j.ang -= 2.2 * dt
            j.mover(self.mapa, adel, lat, dt)
            if j.caminando:
                self.t_bob += dt * 9
            for o in self.objetos:
                if o.recogido or math.hypot(o.x - j.x, o.y - j.y) > 0.6:
                    continue
                if o.tipo == "bidon" and j.bidones < 3:
                    o.recogido = True
                    j.bidones += 1
                    self.sonido.tocar("recoger")
                    self.msg("Bidon recogido (%d/3)" % j.bidones, 2.0)
                elif o.tipo == "balas" and j.balas < 12:
                    o.recogido = True
                    j.balas += 1
                    self.sonido.tocar("recoger")
                    self.msg("Cartucho recogido", 2.0)

        # Anomalias: aparicion
        for a in self.anomalias:
            a.actualizar(dt)
        self.t_anomalia -= dt
        if self.t_anomalia <= 0:
            n = self.noche
            if n < NOCHE_FINAL:
                max_act, intervalo = 1 + n // 2, max(10.0, 30.0 - 4.0 * n)
                permitido = len(self.anomalias) < max_act
            else:
                max_act, intervalo = 3, 5.0
                permitido = (len(self.anomalias) < max_act
                             and self.eliminadas + len(self.anomalias) < OBJETIVO_CAZA)
            if permitido:
                self._aparecer_anomalia()
            self.t_anomalia = intervalo

        self.sombra.actualizar(dt, self)
        if self.estado != "juego":
            return

        # Cordura
        drena = 0.0
        if not gen.encendido:
            drena += 3.0
        drena += (0.7 if self.noche < NOCHE_FINAL else 0.3) * len(self.anomalias)
        if en_dep:
            for a in self.anomalias:
                d = math.hypot(a.x - j.x, a.y - j.y)
                if d < 6 and self.mapa.visible_desde(j.x, j.y, j.ang, MITAD_FOV + 0.2, a.x, a.y, 7):
                    drena += 3.0
            s = self.sombra
            if s.estado == "acechando" and math.hypot(s.x - j.x, s.y - j.y) < 5 \
                    and self.mapa.linea_libre(s.x, s.y, j.x, j.y):
                drena += 2.5
        if drena > 0:
            j.cordura = max(0.0, j.cordura - drena * dt)
        elif gen.encendido:
            j.cordura = min(100.0, j.cordura + (0.2 if en_dep else 0.8) * dt)
        if j.cordura <= 0:
            self.cero_cordura += dt
            if self.cero_cordura > 5.0:
                self.matar("cordura")
                return
        else:
            self.cero_cordura = 0.0

        # Alucinaciones con poca cordura
        self.alucina = max(0.0, self.alucina - dt)
        if j.cordura < 40 and self.alucina <= 0 and random.random() < dt * 0.6 * (1 - j.cordura / 40):
            self.alucina = 0.25
            self.alucina_pos = (random.randint(80, ANCHO - 80), random.randint(100, ALTO - 150))

        # Victoria en la noche 6
        if self.noche >= NOCHE_FINAL and self.eliminadas >= OBJETIVO_CAZA:
            self.estado = "victoria"
            self.sonido.parar()
            self._modo_raton(False)

    def _aparecer_anomalia(self):
        j = self.jugador
        cerca_camara = self.noche < NOCHE_FINAL and random.random() < 0.7
        for _ in range(60):
            cx, cy = random.choice(self.mapa.libres)
            x, y = cx + 0.5, cy + 0.5
            if math.hypot(x - SPAWN[0], y - SPAWN[1]) < 3.5:
                continue
            if self.modo == "deposito" and math.hypot(x - j.x, y - j.y) < (6 if self.noche >= NOCHE_FINAL else 4):
                continue
            if cerca_camara and not any(
                    self.mapa.visible_desde(c["pos"][0], c["pos"][1], c["ang"], MITAD_FOV, x, y, 20)
                    for c in CAMARAS):
                continue
            self.anomalias.append(Anomalia(x, y))
            self.sonido.tocar("alerta")
            return

    # ------------------------------------------------------------------ render pseudo-3D
    def render_vista(self, destino, rect, px, py, ang, sprites, fog, tinte, brillo, colw=COLW):
        """Raycasting + sprites (billboards con z-buffer). Dibuja dentro de 'rect'."""
        W, H = rect.w, rect.h
        ox, oy = rect.x, rect.y
        destino.set_clip(rect)
        mitad = H // 2
        banda = 8

        def tint(v):
            return (min(255, int(v * tinte[0])), min(255, int(v * tinte[1])), min(255, int(v * tinte[2])))

        for y in range(0, mitad, banda):
            t = y / mitad
            destino.fill(tint((4 + 16 * t) * brillo), (ox, oy + y, W, banda))                 # techo
            destino.fill(tint((8 + 26 * t) * brillo), (ox, oy + mitad + y, W, banda))         # suelo

        dirx, diry = math.cos(ang), math.sin(ang)
        plx, ply = -diry * PLANO, dirx * PLANO
        ncol = W // colw
        zbuf = [0.0] * ncol
        lanzar = self.mapa.lanzar_rayo
        for i in range(ncol):
            cx = 2.0 * (i + 0.5) / ncol - 1.0
            dist, lado, tipo, frac = lanzar(px, py, dirx + plx * cx, diry + ply * cx)
            if dist < 0.05:
                dist = 0.05
            zbuf[i] = dist
            if dist >= fog:
                continue
            luz = (1.0 - dist / fog) * brillo
            if lado:
                luz *= 0.72
            if tipo == 2 and int(frac * 8) % 2 == 0:
                luz *= 0.78                      # chapa corrugada de los contenedores
            elif tipo == 1 and (frac < 0.03 or frac > 0.97):
                luz *= 0.7                       # juntas del hormigon
            base = COLORES_MURO.get(tipo, (100, 100, 100))
            lh = int(H / dist)
            color = (min(255, int(base[0] * luz * tinte[0])),
                     min(255, int(base[1] * luz * tinte[1])),
                     min(255, int(base[2] * luz * tinte[2])))
            destino.fill(color, (ox + i * colw, oy + mitad - lh // 2, colw, lh))

        # Sprites ordenados de lejos a cerca
        det = plx * diry - dirx * ply
        if det != 0:
            inv = 1.0 / det
            lista = []
            for (sx, sy, surf, alt, elev) in sprites:
                rx, ry = sx - px, sy - py
                tx = inv * (diry * rx - dirx * ry)
                ty = inv * (-ply * rx + plx * ry)
                if ty >= 0.15:
                    lista.append((ty, tx, surf, alt, elev))
            lista.sort(key=lambda e: -e[0])
            for ty, tx, surf, alt, elev in lista:
                if ty > fog:
                    continue
                pantx = int((W / 2) * (1 + tx / ty))
                tam = int(H * alt / ty)
                if tam < 2 or tam > H * 3:
                    continue
                suelo_y = mitad + int(H / ty / 2) - int(elev * H / ty)
                top = suelo_y - tam
                img = pygame.transform.scale(surf, (tam, tam))
                f = max(0.0, 1.0 - ty / fog) * brillo
                img.fill((int(255 * f * min(1, tinte[0])), int(255 * f * min(1, tinte[1])),
                          int(255 * f * min(1, tinte[2])), 255), special_flags=pygame.BLEND_RGBA_MULT)
                x0 = pantx - tam // 2
                c_ini = max(0, x0 // colw)
                c_fin = min(ncol - 1, (x0 + tam) // colw)
                inicio = None
                for c in range(c_ini, c_fin + 1):
                    visible = zbuf[c] > ty
                    if visible and inicio is None:
                        inicio = c
                    if inicio is not None and (not visible or c == c_fin):
                        fin = c if visible else c - 1
                        xa, xb = max(inicio * colw, x0), min((fin + 1) * colw, x0 + tam)
                        if xb > xa:
                            destino.blit(img, (ox + xa, oy + top), (xa - x0, 0, xb - xa, tam))
                        inicio = None
        destino.set_clip(None)

    # ------------------------------------------------------------------ dibujo de escenas
    def _sprites_entidades(self):
        lista = []
        for a in self.anomalias:
            bob = 0.06 * math.sin(self.t_global * 2 + a.fase)
            img = self.imgs["anomalia%d" % (int(self.t_global * 6 + a.fase) % 2)]
            lista.append((a.x, a.y, img, 0.65, 0.3 + bob))
        if self.sombra.presente:
            lista.append((self.sombra.x, self.sombra.y, self.imgs["sombra"], 1.0, 0.0))
        return lista

    def _sprites_mundo(self):
        lista = []
        for o in self.objetos:
            if not o.recogido:
                lista.append((o.x, o.y, self.imgs[o.tipo], 0.35 if o.tipo == "bidon" else 0.28, 0.0))
        return lista + self._sprites_entidades()

    def dibujar_escopeta(self, bob_x=0, bob_y=0):
        p, j = self.pantalla, self.jugador
        oy = int(j.retroceso * 38) + bob_y
        ox = bob_x
        # Culata y bomba (se desliza al recargar)
        pygame.draw.polygon(p, (92, 58, 32), [(392 + ox, 600), (548 + ox, 600), (520 + ox, 570), (420 + ox, 570)])
        bomba = int(14 * math.sin(min(1.0, j.enfriamiento / 0.9) * math.pi)) if j.enfriamiento > 0 else 0
        pygame.draw.polygon(p, (112, 72, 40), [(414 + ox, 562 + oy + bomba), (526 + ox, 562 + oy + bomba),
                                               (514 + ox, 496 + oy + bomba), (426 + ox, 496 + oy + bomba)])
        # Canon
        pygame.draw.polygon(p, (62, 64, 72), [(424 + ox, 600), (516 + ox, 600), (494 + ox, 410 + oy), (446 + ox, 410 + oy)])
        pygame.draw.line(p, (30, 31, 36), (470 + ox, 600), (470 + ox, 410 + oy), 3)
        pygame.draw.line(p, (110, 112, 122), (436 + ox, 600), (452 + ox, 412 + oy), 2)
        pygame.draw.ellipse(p, (18, 18, 20), (446 + ox, 404 + oy, 48, 12))
        if j.retroceso > 0.75:      # fogonazo
            cx, cy = 470 + ox, 396 + oy
            pts = []
            for i in range(12):
                r = 70 if i % 2 == 0 else 28
                a = i * math.pi / 6
                pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
            pygame.draw.polygon(p, (255, 170, 40), pts)
            pygame.draw.circle(p, (255, 245, 200), (cx, cy), 24)

    def dibujar_oficina(self):
        p, luz = self.pantalla, self.gen.encendido
        p.fill((20, 22, 30) if luz else (5, 5, 8))
        for x in range(0, ANCHO, 100):
            pygame.draw.line(p, (28, 31, 42) if luz else (8, 8, 12), (x, 0), (x, 420), 2)
        pygame.draw.rect(p, (62, 44, 30) if luz else (14, 10, 8), (0, 420, ANCHO, 180))
        pygame.draw.rect(p, (84, 60, 40) if luz else (20, 15, 12), (0, 420, ANCHO, 8))

        # Monitor con la camara actual (renderizada con el mismo motor pseudo-3D)
        pygame.draw.rect(p, (32, 32, 38), (100, 36, 600, 372), border_radius=10)
        pygame.draw.rect(p, (6, 6, 8), MON.inflate(6, 6))
        if luz:
            cam = CAMARAS[self.cam]
            self.render_vista(p, MON, cam["pos"][0], cam["pos"][1], cam["ang"],
                              self._sprites_entidades(), 16.0, (0.35, 1.0, 0.5), 0.95)
            glitch = any(self.mapa.visible_desde(cam["pos"][0], cam["pos"][1], cam["ang"], MITAD_FOV,
                                                 a.x, a.y, 24) for a in self.anomalias)
            r = self.ruido_cam[random.randrange(4)]
            r.set_alpha(100 if glitch else 18)
            p.blit(r, MON.topleft)
            if glitch and random.random() < 0.5:
                for _ in range(3):
                    gy = random.randint(MON.top, MON.bottom - 6)
                    pygame.draw.rect(p, (180, 255, 190), (MON.x, gy, MON.w, random.randint(1, 4)))
            p.set_clip(MON)
            p.blit(self.scan, (0, 0))
            p.set_clip(None)
            self.texto(cam["nombre"], self.f_peq, (170, 255, 180), (MON.x + 10, MON.y + 8))
            pygame.draw.circle(p, (230, 40, 40) if int(self.t_global * 2) % 2 == 0 else (90, 10, 10),
                               (MON.right - 70, MON.y + 16), 6)
            self.texto("REC", self.f_peq, (230, 80, 80), (MON.right - 58, MON.y + 8))
            hora = self.hora_texto() if self.noche < NOCHE_FINAL else "CAZA"
            self.texto("NOCHE %d  %s" % (self.noche, hora), self.f_peq, (170, 255, 180),
                       (MON.x + 10, MON.bottom - 24))
        else:
            self.texto("SIN ENERGIA", self.f_gra, (170, 30, 30), MON.center, True)

        # Botones del monitor
        for i, r in enumerate(self.botones):
            activo = i == self.cam
            pygame.draw.rect(p, (40, 120, 60) if activo else (35, 45, 40), r, border_radius=4)
            pygame.draw.rect(p, (120, 220, 140), r, 1, border_radius=4)
            self.texto("CAM %d" % (i + 1), self.f_peq, (220, 255, 225), r.center, True)
        pygame.draw.rect(p, (120, 50, 40), self.boton_reportar, border_radius=4)
        pygame.draw.rect(p, (240, 130, 110), self.boton_reportar, 1, border_radius=4)
        self.texto("REPORTAR", self.f_peq, (255, 225, 215), self.boton_reportar.center, True)

        # Generador (izquierda)
        g = pygame.Rect(10, 220, 86, 190)
        pygame.draw.rect(p, (48, 58, 48) if luz else (16, 18, 16), g, border_radius=6)
        pygame.draw.rect(p, (90, 110, 90) if luz else (30, 34, 30), g, 2, border_radius=6)
        self.texto("GEN", self.f_peq, (200, 220, 200) if luz else (80, 90, 80), (g.x + 8, g.y + 8))
        led = (60, 255, 90) if luz else ((255, 40, 40) if int(self.t_global * 3) % 2 == 0 else (80, 10, 10))
        pygame.draw.circle(p, led, (g.right - 16, g.y + 16), 6)
        barra = pygame.Rect(g.x + 12, g.y + 36, 24, 120)
        pygame.draw.rect(p, (10, 10, 10), barra)
        alto = int(barra.h * self.gen.nivel / 100)
        col = (230, 170, 30) if self.gen.nivel > 25 else (230, 50, 40)
        pygame.draw.rect(p, col, (barra.x, barra.bottom - alto, barra.w, alto))
        pygame.draw.rect(p, (150, 150, 150), barra, 1)
        self.texto("%d%%" % int(self.gen.nivel), self.f_peq, (230, 230, 230), (g.x + 44, g.y + 90))
        for i in range(self.jugador.bidones):
            pygame.draw.rect(p, (175, 32, 26), (g.x + 8 + i * 24, g.bottom - 26, 18, 20), border_radius=2)

        # Puerta / ventana (derecha) donde aparece la Sombra
        d = pygame.Rect(712, 60, 78, 350)
        pygame.draw.rect(p, (14, 14, 20), d.inflate(10, 10))
        pygame.draw.rect(p, (2, 2, 4), d)
        if self.sombra.estado == "puerta":
            if luz:
                p.set_clip(d)
                p.blit(pygame.transform.scale(self.imgs["sombra"], (150, 340)), (d.centerx - 75, d.y + 10))
                p.set_clip(None)
            for ex in (-12, 12):
                pygame.draw.circle(p, (110, 0, 0), (d.centerx + ex, d.y + 74), 8)
                pygame.draw.circle(p, (255, 40, 30), (d.centerx + ex, d.y + 74), 4)
            if int(self.t_global * 4) % 2 == 0:
                self.texto("¡DISPARA!", self.f_med, (255, 60, 50), (d.centerx, d.bottom + 16), True)

        if not luz:   # lampara de emergencia
            rojo = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
            rojo.fill((120, 0, 0, 14 + int(14 * math.sin(self.t_global * 3))))
            p.blit(rojo, (0, 0))

        # Ayuda y escopeta
        for i, s in enumerate(("[1][2][3] Camaras    [R] Reportar", "[F] Verter bidon (llevas %d)" % self.jugador.bidones,
                               "[E] Salir al deposito", "[ESPACIO/CLIC] Disparar")):
            self.texto(s, self.f_peq, (190, 170, 140), (12, 470 + i * 22))
        self.dibujar_escopeta()

    def dibujar_deposito(self):
        p, j, luz = self.pantalla, self.jugador, self.gen.encendido
        brillo = 1.0 if luz else 0.45
        if luz and j.cordura < 40 and random.random() < 0.08:
            brillo *= 0.5                                   # parpadeo de la luz por locura
        fog = 11.0 if luz else 3.6
        self.render_vista(p, pygame.Rect(0, 0, ANCHO, ALTO), j.x, j.y, j.ang,
                          self._sprites_mundo(), fog, (1.0, 1.0, 1.0), brillo)
        bob_x = int(math.sin(self.t_bob) * 7) if j.caminando else 0
        bob_y = int(abs(math.cos(self.t_bob)) * 6) if j.caminando else 0
        self.dibujar_escopeta(bob_x, bob_y)
        pygame.draw.line(p, (220, 220, 220), (ANCHO // 2 - 8, ALTO // 2), (ANCHO // 2 + 8, ALTO // 2), 1)
        pygame.draw.line(p, (220, 220, 220), (ANCHO // 2, ALTO // 2 - 8), (ANCHO // 2, ALTO // 2 + 8), 1)
        if math.hypot(j.x - SPAWN[0], j.y - SPAWN[1]) < 1.8:
            self.texto("[E] Entrar a la oficina", self.f_med, (120, 255, 150), (ANCHO // 2, ALTO - 110), True)
        self.texto("WASD mover  RATON girar  CLIC disparar  E oficina",
                   self.f_peq, (150, 150, 150), (12, ALTO - 24))

    def dibujar_infinito(self, cx, cy, color):
        pygame.draw.circle(self.pantalla, color, (cx - 7, cy), 7, 2)
        pygame.draw.circle(self.pantalla, color, (cx + 7, cy), 7, 2)

    def barra(self, etiqueta, x, y, ancho, valor, color):
        p = self.pantalla
        self.texto(etiqueta, self.f_peq, (210, 210, 210), (x, y))
        bx = x + 92
        pygame.draw.rect(p, (20, 20, 20), (bx, y + 1, ancho, 14))
        pygame.draw.rect(p, color, (bx, y + 1, int(ancho * max(0, valor) / 100), 14))
        pygame.draw.rect(p, (170, 170, 170), (bx, y + 1, ancho, 14), 1)
        self.texto("%d%%" % int(valor), self.f_peq, (240, 240, 240), (bx + ancho + 6, y))

    def dibujar_hud(self):
        p, j = self.pantalla, self.jugador
        panel = pygame.Surface((ANCHO, 52), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 150))
        p.blit(panel, (0, 0))
        self.texto("NOCHE %d" % self.noche, self.f_med, (235, 235, 235), (10, 3))
        if self.noche < NOCHE_FINAL:
            self.texto(self.hora_texto(), self.f_med, (255, 220, 120), (150, 3))
        else:
            self.texto("CAZA %d/%d" % (self.eliminadas, OBJETIVO_CAZA), self.f_med, (255, 90, 80), (150, 3))
        self.texto("BALAS", self.f_peq, (200, 200, 200), (320, 7))
        if self.noche >= NOCHE_FINAL:
            self.dibujar_infinito(400, 15, (255, 220, 120))
        else:
            self.texto(str(j.balas), self.f_med, (255, 220, 120), (385, 3))
        self.texto("BIDONES %d/3" % j.bidones, self.f_peq, (200, 200, 200), (470, 7))
        gas_col = (235, 175, 30) if self.gen.nivel > 25 else (235, 55, 40)
        self.barra("GASOLINA", 10, 31, 130, self.gen.nivel, gas_col)
        cor_col = (90, 170, 255) if j.cordura > 35 else (235, 55, 40)
        self.barra("CORDURA", 400, 31, 130, j.cordura, cor_col)
        for i, (s, t) in enumerate(self.mensajes):
            self.texto(s, self.f_med, (255, 235, 150), (ANCHO // 2, 76 + i * 26), True)

    def dibujar_efectos(self):
        p, j = self.pantalla, self.jugador
        if self.flash > 0:
            f = pygame.Surface((ANCHO, ALTO))
            f.fill((255, 240, 200))
            f.set_alpha(int(200 * self.flash / 0.18))
            p.blit(f, (0, 0))
        if j.cordura < 50 or not self.gen.encendido:
            nivel = max(0, 50 - j.cordura) * 2.2 + (40 if not self.gen.encendido else 0)
            r = self.ruido_full[random.randrange(4)]
            r.set_alpha(int(min(150, nivel)))
            p.blit(r, (0, 0))
        if j.cordura < 60:
            rojo = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
            rojo.fill((150, 0, 0, int((60 - j.cordura) * 1.2)))
            p.blit(rojo, (0, 0))
        self.scan.set_alpha(90)
        p.blit(self.scan, (0, 0))
        p.blit(self.vineta, (0, 0))
        if self.alucina > 0:
            x, y = self.alucina_pos
            for ex in (-14, 14):
                pygame.draw.ellipse(p, (230, 20, 20), (x + ex - 8, y - 5, 16, 10))
                pygame.draw.circle(p, (255, 255, 255), (x + ex, y), 2)

    def dibujar_susto(self):
        p = self.pantalla
        p.fill((0, 0, 0))
        sx = random.randint(-14, 14)
        cx = ANCHO // 2 + sx
        pygame.draw.ellipse(p, (14, 14, 16), (cx - 270, 30, 540, 580))
        for ex in (-120, 70):
            pygame.draw.ellipse(p, (255, 30, 20), (cx + ex, 190, 100, 54))
            pygame.draw.circle(p, (255, 255, 255), (cx + ex + 50, 217), 6)
        dientes = []
        for i in range(11):
            dientes += [(cx - 150 + i * 30, 420 + (40 if i % 2 else 0))]
        pygame.draw.polygon(p, (235, 235, 225), [(cx - 160, 400)] + dientes + [(cx + 160, 400)])
        if int(self.t_global * 20) % 2 == 0:
            rojo = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
            rojo.fill((255, 0, 0, 60))
            p.blit(rojo, (0, 0))
        r = self.ruido_full[random.randrange(4)]
        r.set_alpha(110)
        p.blit(r, (0, 0))

    def dibujar_menu(self):
        p = self.pantalla
        p.fill((6, 6, 10))
        r = self.ruido_full[int(self.t_global * 8) % 4]
        r.set_alpha(28)
        p.blit(r, (0, 0))
        self.texto("TURNO NOCTURNO", self.f_tit, (210, 40, 40), (ANCHO // 2, 90), True)
        self.texto("EN EL DEPOSITO 8", self.f_gra, (225, 225, 225), (ANCHO // 2, 150), True)
        lineas = [
            "Sobrevive 6 noches (12:00 AM - 6:00 AM) como guardia del almacen.",
            "Vigila las camaras, reporta anomalias y manten el generador con gasolina.",
            "Sal al deposito por bidones y cartuchos... pero la Sombra te busca.",
            "Noche 6: balas infinitas. Elimina %d anomalias para ganar." % OBJETIVO_CAZA,
            "",
            "OFICINA:  1/2/3 camaras | R reportar | F verter bidon | E salir | ESPACIO disparar",
            "DEPOSITO: WASD mover | RATON/FLECHAS girar | CLIC disparar | E volver (junto a la puerta)",
        ]
        for i, s in enumerate(lineas):
            self.texto(s, self.f_peq, (190, 190, 190), (ANCHO // 2, 240 + i * 28), True)
        if int(self.t_global * 2) % 2 == 0:
            self.texto("ENTER para empezar    |    ESC para salir", self.f_med, (255, 220, 120),
                       (ANCHO // 2, 500), True)

    def dibujar_pantalla_texto(self, titulo, color, lineas):
        p = self.pantalla
        p.fill((4, 4, 6))
        self.texto(titulo, self.f_gra, color, (ANCHO // 2, 200), True)
        for i, s in enumerate(lineas):
            self.texto(s, self.f_med, (210, 210, 210), (ANCHO // 2, 280 + i * 36), True)

    def dibujar(self):
        e = self.estado
        if e == "menu":
            self.dibujar_menu()
        elif e == "susto":
            self.dibujar_susto()
        elif e == "intro":
            if self.noche >= NOCHE_FINAL:
                self.dibujar_pantalla_texto("NOCHE 6 - MODO CAZA", (230, 50, 50),
                                            ["Balas infinitas", "Elimina %d anomalias en el deposito" % OBJETIVO_CAZA,
                                             "La Sombra no se detendra."])
                self.dibujar_infinito(ANCHO // 2 + 130, 288, (255, 220, 120))
            else:
                self.dibujar_pantalla_texto("NOCHE %d" % self.noche, (225, 225, 225),
                                            ["12:00 AM", "Aguanta hasta las 6:00 AM"])
        elif e == "gameover":
            causas = {"sombra": "La Sombra te dio alcance en el deposito.",
                      "puerta": "La Sombra entro por la puerta de la oficina.",
                      "cordura": "Perdiste la cordura en la oscuridad."}
            self.dibujar_pantalla_texto("HAS MUERTO", (210, 40, 40),
                                        [causas.get(self.causa, ""), "ENTER: reintentar la noche %d" % self.noche,
                                         "ESC: menu"])
        elif e == "noche_superada":
            sig = "ENTER: continuar a la noche %d" % (self.noche + 1)
            self.dibujar_pantalla_texto("6:00 AM", (255, 220, 120),
                                        ["Sobreviviste a la noche %d." % self.noche, sig])
        elif e == "victoria":
            self.dibujar_pantalla_texto("AMANECE", (120, 255, 150),
                                        ["Cazaste a las anomalias del Deposito 8.", "Has sobrevivido. Fin.",
                                         "ENTER: volver al menu"])
        else:
            if self.modo == "oficina":
                self.dibujar_oficina()
            else:
                self.dibujar_deposito()
            self.dibujar_efectos()
            self.dibujar_hud()
        pygame.display.flip()

    # ------------------------------------------------------------------ bucle principal
    def ejecutar(self):
        while self.running:
            dt = min(self.reloj.tick(FPS) / 1000.0, 0.05)
            self.procesar_eventos()
            self.actualizar(dt)
            self.dibujar()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    GameManager().ejecutar()