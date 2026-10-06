"""Worker de INVENTARIO: reservar-stock / liberar-stock."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun import Servicio, cargar_env, conectar, ejecutar  # noqa: E402

cargar_env()

from pyzeebe.errors import BusinessError  # noqa: E402

from comun.base import tarea  # noqa: E402

svc = Servicio("inventario")
worker = conectar()
stock = {"notebook": 10, "celular": 10, "monitor": 5}  # propiedad exclusiva de este servicio
reservas: dict[str, tuple[str, int]] = {}  # pedidoId -> (producto, cantidad) reservado


@tarea(worker, svc, "reservar-stock", info=lambda: f"stock actual: {stock}")
async def reservar_stock(v):
    pedido, prod, cant = str(v["pedidoId"]), v.get("producto"), int(v.get("cantidad", 1))
    svc.log(f"Reservando {cant} {prod} para el pedido {pedido}... (stock: {stock.get(prod)})")
    await svc.trabajar()
    await svc.simular_falla("reservar-stock", v, "SIN_STOCK", "sin stock")
    if stock.get(prod, 0) < cant:
        svc.log(f"Pedido {pedido}: stock insuficiente de {prod} ({stock.get(prod, 0)} < {cant})", "ERROR")
        raise BusinessError("SIN_STOCK", f"No hay stock de {prod}")
    antes = stock[prod]
    stock[prod] -= cant
    reservas[pedido] = (prod, cant)
    svc.log(f"Pedido {pedido}: reservado. Stock {prod}: {antes} -> {stock[prod]}", "OK")
    return {"stockReservado": True}


@tarea(worker, svc, "liberar-stock")
async def liberar_stock(v):
    pedido = str(v["pedidoId"])
    prod, cant = reservas.pop(pedido, (None, 0))
    if prod is None:
        svc.log(f"Compensación: el pedido {pedido} no tiene reserva, nada que liberar", "COMP")
        return {"stockLiberado": False}
    svc.log(f"Compensación: liberando {cant} {prod} del pedido {pedido}...", "COMP")
    await svc.trabajar()
    antes = stock[prod]
    stock[prod] += cant
    svc.log(f"Compensación: liberando {cant} {prod} del pedido {pedido}. Stock: {antes} -> {stock[prod]}", "OK")
    return {"stockLiberado": True}


if __name__ == "__main__":
    ejecutar(svc, worker, ["reservar-stock", "liberar-stock"])
