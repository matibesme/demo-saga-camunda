"""Worker de ENVIOS: programar-envio (último paso, sin compensación)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun import Servicio, cargar_env, conectar, ejecutar  # noqa: E402

cargar_env()

from comun.base import tarea  # noqa: E402

svc = Servicio("envios")
worker = conectar()
envios: dict[str, str] = {}  # pedidoId -> envioId


@tarea(worker, svc, "programar-envio")
async def programar_envio(v):
    pedido = str(v["pedidoId"])
    svc.log(f"Programando envío del pedido {pedido}...")
    await svc.trabajar()
    await svc.simular_falla("programar-envio", v, "ENVIO_NO_DISPONIBLE", "sin cobertura de envío")
    envios[pedido] = f"ENV-{pedido}"
    svc.log(f"Pedido {pedido}: envío {envios[pedido]} programado. Envíos: {len(envios)}", "OK")
    return {"envioId": envios[pedido]}


if __name__ == "__main__":
    ejecutar(svc, worker, ["programar-envio"])
