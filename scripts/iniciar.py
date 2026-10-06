#!/usr/bin/env python3
"""Despliega el BPMN (si hace falta) y crea instancias del proceso de compra.

  iniciar.py feliz                 todo sale bien
  iniciar.py falla-cobro           error de negocio en cobrar   -> compensa stock y orden
  iniciar.py falla-envio           error de negocio en envío    -> compensa todo
  iniciar.py falla-stock           error de negocio en reservar -> compensa la orden
  iniciar.py falla-tecnica-cobro   falla técnica en cobrar      -> reintentos -> incidente
  iniciar.py duplicado             cobrar tarda más que el job timeout -> job entregado 2 veces (idempotencia)
  iniciar.py lote 5                5 instancias felices seguidas
  iniciar.py acreditar <pedidoId>  publica "pago-acreditado" (solo con --con-acreditacion)

Opciones: --con-acreditacion usa compra-con-acreditacion.bpmn (extensión opcional).
"""
import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "workers"))
from comun import cargar_env  # noqa: E402
from comun.base import crear_canal  # noqa: E402

cargar_env()

ESCENARIOS = {
    "feliz": ("ninguno", "negocio"),
    "falla-stock": ("reservar-stock", "negocio"),
    "falla-cobro": ("cobrar", "negocio"),
    "falla-envio": ("programar-envio", "negocio"),
    "falla-tecnica-cobro": ("cobrar", "tecnica"),
    "duplicado": ("cobrar", "lento"),
    "falla-tecnica-envio": ("programar-envio", "tecnica"),
}


def siguiente_pedido(n: int) -> int:
    """Reserva n pedidoId consecutivos y únicos (contador en .pedidos, que no se versiona)."""
    f = RAIZ / ".pedidos"
    base = int(f.read_text()) if f.exists() else 100
    f.write_text(str(base + n))
    return base


async def main(args: list[str]) -> int:
    acred = "--con-acreditacion" in args
    args = [a for a in args if not a.startswith("--")]
    if not args or args[0] in ("-h", "help") or (args[0] not in ESCENARIOS and args[0] not in ("lote", "acreditar")):
        print(__doc__)
        return 2

    from pyzeebe import ZeebeClient

    cliente = ZeebeClient(crear_canal())
    proceso = "compra-con-acreditacion" if acred else "compra"
    bpmn = RAIZ / "bpmn" / f"{proceso}.bpmn"

    if args[0] == "acreditar":
        pedido = args[1]
        await cliente.publish_message("pago-acreditado", pedido, {"acreditado": True})
        print(f"Mensaje 'pago-acreditado' publicado para el pedido {pedido}")
        return 0

    await cliente.deploy_resource(str(bpmn))
    print(f"BPMN desplegado: {bpmn.name}")

    if args[0] == "lote":
        n = int(args[1]) if len(args) > 1 else 5
        plan = [("ninguno", "negocio")] * n
    else:
        plan = [ESCENARIOS[args[0]]]

    base = siguiente_pedido(len(plan))
    for i, (fallar_en, tipo) in enumerate(plan):
        pedido = str(base + i)
        r = await cliente.run_process(proceso, {
            "pedidoId": pedido, "monto": 5000, "producto": "notebook", "cantidad": 1,
            "fallarEn": fallar_en, "tipoFalla": tipo,
        })
        print(f"Instancia {r.process_instance_key} creada: pedidoId={pedido} fallarEn={fallar_en} tipoFalla={tipo}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
