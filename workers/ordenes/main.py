"""Worker de ORDENES: crear-orden / cancelar-orden."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun import Servicio, cargar_env, conectar, ejecutar  # noqa: E402

cargar_env()

from comun.base import tarea  # noqa: E402

svc = Servicio("ordenes")
worker = conectar()
ordenes: dict[str, str] = {}  # pedidoId -> estado (propiedad exclusiva de este servicio)


@tarea(worker, svc, "crear-orden")
async def crear_orden(v):
    pedido = str(v["pedidoId"])
    svc.log(f"Creando orden del pedido {pedido} ({v.get('cantidad')} x {v.get('producto')})...")
    await svc.trabajar()
    await svc.simular_falla("crear-orden", v, "ORDEN_INVALIDA", "datos de la orden inválidos")
    ordenes[pedido] = "CREADA"
    svc.log(f"Pedido {pedido}: orden CREADA. Órdenes activas: {sum(e == 'CREADA' for e in ordenes.values())}", "OK")
    return {"ordenCreada": True}


@tarea(worker, svc, "cancelar-orden")
async def cancelar_orden(v):
    pedido = str(v["pedidoId"])
    svc.log(f"Compensación: cancelando orden del pedido {pedido}...", "COMP")
    await svc.trabajar()
    ordenes[pedido] = "CANCELADA"
    svc.log(f"Pedido {pedido}: orden CANCELADA. Órdenes activas: {sum(e == 'CREADA' for e in ordenes.values())}", "OK")
    return {"ordenCancelada": True}


if __name__ == "__main__":
    ejecutar(svc, worker, ["crear-orden", "cancelar-orden"])
