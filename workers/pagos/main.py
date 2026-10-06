"""Worker de PAGOS: cobrar / reembolsar."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from comun import Servicio, cargar_env, conectar, ejecutar  # noqa: E402

cargar_env()

from comun.base import tarea  # noqa: E402

svc = Servicio("pagos")
worker = conectar()
cobros: dict[str, dict] = {}  # pedidoId -> {"cobroId", "monto", "estado"}


def saldo() -> int:
    return sum(c["monto"] for c in cobros.values() if c["estado"] == "COBRADO")


@tarea(worker, svc, "cobrar", info=lambda: f"recaudado: ${saldo()}")
async def cobrar(v):
    pedido, monto = str(v["pedidoId"]), v.get("monto")
    svc.log(f"Cobrando pedido {pedido} por ${monto}...")
    await svc.trabajar()
    await svc.simular_falla("cobrar", v, "PAGO_RECHAZADO", "pago rechazado por el banco")
    cobros[pedido] = {"cobroId": f"COB-{pedido}", "monto": monto, "estado": "COBRADO"}
    svc.log(f"Cobrando pedido {pedido} por ${monto}... OK. Recaudado: ${saldo()}", "OK")
    return {"cobroId": f"COB-{pedido}"}


@tarea(worker, svc, "reembolsar")
async def reembolsar(v):
    pedido = str(v["pedidoId"])
    cobro = cobros.get(pedido)
    if not cobro:
        svc.log(f"Compensación: el pedido {pedido} no tiene cobro, nada que reembolsar", "COMP")
        return {"cobroReembolsado": False}
    svc.log(f"Compensación: reembolsando ${cobro['monto']} del pedido {pedido}...", "COMP")
    await svc.trabajar()
    cobro["estado"] = "REEMBOLSADO"
    svc.log(f"Compensación: reembolsado ${cobro['monto']} del pedido {pedido}. Recaudado: ${saldo()}", "OK")
    return {"cobroReembolsado": True}


if __name__ == "__main__":
    ejecutar(svc, worker, ["cobrar", "reembolsar"])
