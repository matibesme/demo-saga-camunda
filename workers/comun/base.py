"""Código compartido por los cuatro workers: conexión a Zeebe, logging,
simulación de trabajo/fallas e idempotencia."""
import asyncio
import logging
import os
import socket
import sys
from pathlib import Path

import grpc
from pyzeebe import (
    Job,
    JobController,
    ZeebeTaskRouter,
    ZeebeWorker,
    create_insecure_channel,
    create_oauth2_client_credentials_channel,
)
from pyzeebe.errors import BusinessError, JobNotFoundError

RAIZ = Path(__file__).resolve().parents[2]

# Timeout corto: si un worker toma un job y se cae, el job vuelve a estar
# disponible a los 25 s (el default de pyzeebe son 10 s, Zeebe usa 5 min).
JOB_TIMEOUT_MS = int(os.getenv("JOB_TIMEOUT_MS", "25000"))
# Cuántas veces falla técnicamente un job antes de funcionar (ver simular_falla).
FALLAS_TECNICAS = int(os.getenv("FALLAS_TECNICAS", "3"))
BACKOFF_MS = int(os.getenv("RETRY_BACKOFF_MS", "2000"))

RESET, BOLD, DIM = "\033[0m", "\033[1m", "\033[2m"
COLORES = {"ORDENES": "\033[36m", "INVENTARIO": "\033[33m", "PAGOS": "\033[35m", "ENVIOS": "\033[34m"}
VERDE, ROJO, AMARILLO = "\033[32m", "\033[31m", "\033[33m"


def cargar_env() -> None:
    """Carga <repo>/.env sin pisar variables ya definidas (sin dependencias extra)."""
    f = RAIZ / ".env"
    if not f.exists():
        return
    for linea in f.read_text().splitlines():
        linea = linea.strip()
        if linea and not linea.startswith("#") and "=" in linea:
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


class Servicio:
    """Estado propio (en memoria) + logging + idempotencia de un servicio."""

    def __init__(self, nombre: str):
        self.nombre = nombre.upper()
        self.worker = os.getenv("WORKER_NAME") or f"laptop-{socket.gethostname()}"
        self.color = COLORES.get(self.nombre, "")
        self.hechos: dict[tuple[str, str], dict] = {}  # (job_type, pedidoId) -> resultado
        self.intentos_fallidos: dict[tuple[str, str], int] = {}
        self.locks: dict[tuple[str, str], asyncio.Lock] = {}

    # --- logging -------------------------------------------------------
    def log(self, msg: str, estado: str = "") -> None:
        pref = f"{self.color}{BOLD}[{self.nombre} @ {self.worker}]{RESET}"
        col = {"OK": VERDE, "ERROR": ROJO, "FALLA": ROJO, "DUPLICADO": AMARILLO, "COMP": AMARILLO}.get(estado, "")
        sufijo = f" {col}{BOLD}{estado}{RESET}" if estado else ""
        print(f"{pref} {msg}{sufijo}", flush=True)

    async def trabajar(self, v: dict | None = None) -> None:
        """Simula 1–2 s de trabajo para que se vea avanzar la instancia en Operate."""
        import random

        await asyncio.sleep(random.uniform(1.0, 2.0))

    # --- idempotencia --------------------------------------------------
    async def una_vez(self, job_type: str, pedido: str, fn, info=None) -> dict:
        """Ejecuta `fn()` una sola vez por (job_type, pedidoId).

        Si Zeebe entrega el mismo job de nuevo (reintento, o timeout con el primer intento
        todavía corriendo) se devuelve el resultado ya calculado sin repetir el efecto.
        El lock serializa las ejecuciones concurrentes del mismo job.
        """
        clave = (job_type, pedido)
        async with self.locks.setdefault(clave, asyncio.Lock()):
            if clave in self.hechos:
                self.log(f"Job '{job_type}' repetido para el pedido {pedido}: se ignora, no se repite el efecto"
                         + (f" ({info()})" if info else ""), "DUPLICADO")
                return self.hechos[clave]
            resultado = await fn()
            self.hechos[clave] = resultado
            return resultado

    # --- simulación de fallas -----------------------------------------
    async def simular_falla(self, job_type: str, v: dict, codigo: str, descripcion: str) -> None:
        """Aplica el escenario pedido por las variables `fallarEn` / `tipoFalla`.

        - negocio: lanza un BPMN error (`codigo`) -> el proceso compensa.
        - lento: tarda más que el job timeout (el job se entrega dos veces).
        - tecnica: falla el job (Zeebe reintenta; sin retries -> incidente).
          Falla las primeras FALLAS_TECNICAS veces (= retries del BPMN) para que, al
          resolver el incidente en Operate, el siguiente intento ya funcione.
        """
        if v.get("fallarEn") != job_type:
            return
        pedido = str(v.get("pedidoId"))
        if v.get("tipoFalla") == "lento":
            # No falla: tarda más que el job timeout, así Zeebe re-entrega el job al mismo worker
            # mientras el primer intento sigue corriendo (para mostrar la idempotencia).
            demora = JOB_TIMEOUT_MS / 1000 + 10
            self.log(f"Pedido {pedido}: trabajo lento ({demora:.0f} s), más que el job timeout...")
            await asyncio.sleep(demora)
            return
        if v.get("tipoFalla", "negocio") == "tecnica":
            k = (job_type, pedido)
            n = self.intentos_fallidos.get(k, 0)
            if n < FALLAS_TECNICAS:
                self.intentos_fallidos[k] = n + 1
                self.log(f"Pedido {pedido}: el servicio externo no responde (falla técnica, intento {n + 1})", "FALLA")
                raise ConnectionError("el servicio externo no responde (simulado)")
            self.log(f"Pedido {pedido}: el servicio externo volvió a responder")
            return
        self.log(f"Pedido {pedido}: {descripcion} -> error de negocio {codigo}", "ERROR")
        raise BusinessError(codigo, descripcion)


async def _manejar_excepcion(e: Exception, job: Job, ctrl: JobController) -> None:
    if isinstance(e, BusinessError):
        await ctrl.set_error_status(str(e), error_code=e.error_code)
    else:
        # Falla técnica: NO es un error BPMN. Zeebe baja `retries`; en 0 crea un incidente.
        await ctrl.set_failure_status(f"{type(e).__name__}: {e}", retry_back_off_ms=BACKOFF_MS)
        print(f"{AMARILLO}   (job {job.type} falló; retries restantes: {job.retries - 1}){RESET}", flush=True)


def conectar() -> ZeebeTaskRouter:
    """Router donde se registran las tareas; el canal gRPC se crea en `ejecutar`
    (tiene que nacer dentro del event loop que lo va a usar)."""
    return ZeebeTaskRouter()


def crear_canal():
    addr = os.getenv("ZEEBE_ADDRESS", "localhost:26500")
    if os.getenv("ZEEBE_CLIENT_ID"):
        return create_oauth2_client_credentials_channel(
            grpc_address=addr,
            client_id=os.environ["ZEEBE_CLIENT_ID"],
            client_secret=os.environ["ZEEBE_CLIENT_SECRET"],
            authorization_server=os.environ["ZEEBE_AUTHORIZATION_SERVER_URL"],
            audience=os.getenv("ZEEBE_TOKEN_AUDIENCE", "zeebe-api"),
        )
    return create_insecure_channel(grpc_address=addr)


def tarea(router: ZeebeTaskRouter, svc: Servicio, job_type: str, info=None):
    """Registra un job con timeout corto, manejo de excepciones común e idempotencia por pedidoId.
    La función decorada recibe las variables (dict) y devuelve las variables de salida."""

    def deco(fn):
        @router.task(task_type=job_type, timeout_ms=JOB_TIMEOUT_MS, exception_handler=_manejar_excepcion)
        async def handler(job: Job):
            v = dict(job.variables)
            return await svc.una_vez(job_type, str(v["pedidoId"]), lambda: fn(v), info)

        return handler

    return deco


class _FiltroJobYaCompletado(logging.Filter):
    """Con un job entregado dos veces, el segundo intento no puede completarlo (el primero ya lo hizo).
    Es esperable: se muestra en una línea en vez de un traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.exc_info and isinstance(record.exc_info[1], JobNotFoundError):
            record.exc_info = None
            record.msg = f"{AMARILLO}(el job ya estaba completado por la ejecución anterior: normal con duplicados){RESET}"
            record.args = ()
        return True


def ejecutar(svc: Servicio, worker: ZeebeTaskRouter, tipos: list[str]) -> None:
    addr = os.getenv("ZEEBE_ADDRESS", "localhost:26500")
    svc.log(f"Conectando a Zeebe en {addr}. Atiende: {', '.join(tipos)}")
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logging.getLogger("pyzeebe.worker.job_executor").addFilter(_FiltroJobYaCompletado())

    async def correr():
        w = ZeebeWorker(crear_canal(), max_connection_retries=-1)
        w.include_router(worker)
        await w.work()

    try:
        asyncio.run(correr())
    except KeyboardInterrupt:
        svc.log("Detenido")
    except grpc.RpcError as e:
        svc.log(f"No pude hablar con Zeebe: {e}", "ERROR")
        sys.exit(1)
