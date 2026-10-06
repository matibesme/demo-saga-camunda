#!/usr/bin/env python3
"""Genera compra.bpmn (y compra-con-acreditacion.bpmn con la extensión opcional).

El .bpmn resultante se edita normalmente con Camunda Modeler; este script solo
evita escribir a mano las coordenadas del diagrama.
Uso: python3 bpmn/generar.py
"""
from pathlib import Path

PASOS = [  # (clave, nombre, job type, código de error de negocio, compensación)
    ("Orden", "Crear orden", "crear-orden", "ORDEN_INVALIDA", ("Cancelar orden", "cancelar-orden")),
    ("Stock", "Reservar stock", "reservar-stock", "SIN_STOCK", ("Liberar stock", "liberar-stock")),
    ("Cobro", "Cobrar", "cobrar", "PAGO_RECHAZADO", ("Reembolsar", "reembolsar")),
    ("Envio", "Programar envío", "programar-envio", "ENVIO_NO_DISPONIBLE", None),
]
W, H, EV = 100, 80, 36
YC = 200  # eje del camino feliz


def generar(acreditacion: bool) -> str:
    pid = "compra" if not acreditacion else "compra-con-acreditacion"
    nodos, flujos, shapes, edges, artefactos = [], [], [], [], []
    errores, x = [], 152

    def shape(i, x, y, w, h, label=None):
        lb = f'<bpmndi:BPMNLabel><dc:Bounds x="{label[0]}" y="{label[1]}" width="{label[2]}" height="{label[3]}" /></bpmndi:BPMNLabel>' if label else ""
        shapes.append(f'<bpmndi:BPMNShape id="{i}_di" bpmnElement="{i}"><dc:Bounds x="{x}" y="{y}" width="{w}" height="{h}" />{lb}</bpmndi:BPMNShape>')

    def edge(i, pts, label=None):
        wp = "".join(f'<di:waypoint x="{a}" y="{b}" />' for a, b in pts)
        edges.append(f'<bpmndi:BPMNEdge id="{i}_di" bpmnElement="{i}">{wp}</bpmndi:BPMNEdge>')

    secuencia = []  # (id, x_izq, ancho, y_centro_entrada/salida)
    nodos.append('<bpmn:startEvent id="Inicio" name="Pedido recibido"><bpmn:outgoing>F_inicio</bpmn:outgoing></bpmn:startEvent>')
    shape("Inicio", x, YC - EV // 2, EV, EV, (x - 20, YC + 24, 76, 27))
    secuencia.append(("Inicio", x, EV))
    x = 250
    for clave, nombre, job, err, comp in PASOS:
        t = f"T_{clave}"
        nodos.append(f'<bpmn:serviceTask id="{t}" name="{nombre}"><bpmn:extensionElements><zeebe:taskDefinition type="{job}" retries="3" /></bpmn:extensionElements></bpmn:serviceTask>')
        shape(t, x, YC - H // 2, W, H)
        secuencia.append((t, x, W))
        # error de negocio (arriba)
        e = f"E_{clave}"
        errores.append(f'<bpmn:error id="Err_{clave}" name="{err}" errorCode="{err}" />')
        nodos.append(f'<bpmn:boundaryEvent id="{e}" name="{err}" attachedToRef="{t}"><bpmn:errorEventDefinition id="ED_{clave}" errorRef="Err_{clave}" /></bpmn:boundaryEvent>')
        shape(e, x + 64, YC - H // 2 - EV // 2, EV, EV, (x - 15, YC - H // 2 - 72, 130, 27))
        if comp:
            c, h = f"C_{clave}", f"H_{clave}"
            nodos.append(f'<bpmn:boundaryEvent id="{c}" name="Compensar {nombre.lower()}" attachedToRef="{t}"><bpmn:compensateEventDefinition id="CD_{clave}" /></bpmn:boundaryEvent>')
            nodos.append(f'<bpmn:serviceTask id="{h}" name="{comp[0]}" isForCompensation="true"><bpmn:extensionElements><zeebe:taskDefinition type="{comp[1]}" retries="3" /></bpmn:extensionElements></bpmn:serviceTask>')
            shape(c, x + 14, YC + H // 2 - EV // 2, EV, EV)
            shape(h, x, YC + 130, W, H)
            artefactos.append(f'<bpmn:association id="A_{clave}" associationDirection="One" sourceRef="{c}" targetRef="{h}" />')
            edge(f"A_{clave}", [(x + 32, YC + H // 2 + EV // 2), (x + 32, YC + 130)])
        x += W + 70
        if clave == "Cobro" and acreditacion:
            nodos.append('<bpmn:intermediateCatchEvent id="Acreditado" name="Pago acreditado"><bpmn:messageEventDefinition id="MD_pago" messageRef="Msg_pago" /></bpmn:intermediateCatchEvent>')
            shape("Acreditado", x, YC - EV // 2, EV, EV, (x - 25, YC + 24, 86, 27))
            secuencia.append(("Acreditado", x, EV))
            x += EV + 70
    nodos.append('<bpmn:endEvent id="FinOk" name="Compra exitosa" />')
    shape("FinOk", x, YC - EV // 2, EV, EV, (x - 22, YC + 24, 80, 27))
    secuencia.append(("FinOk", x, EV))
    x_fin_ok = x

    # flujos del camino feliz
    for n, ((a, ax, aw), (b, bx, _)) in enumerate(zip(secuencia, secuencia[1:])):
        fid = "F_inicio" if a == "Inicio" else f"F_{n}"
        flujos.append(f'<bpmn:sequenceFlow id="{fid}" sourceRef="{a}" targetRef="{b}" />')
        edge(fid, [(ax + aw, YC), (bx, YC)])

    # compensación: todos los errores -> "Compensar" -> fin distinto
    xt, yt = x_fin_ok + 120, 70
    nodos.append('<bpmn:intermediateThrowEvent id="Compensar" name="Compensar pasos completados"><bpmn:compensateEventDefinition id="CD_Compensar" waitForCompletion="true" /></bpmn:intermediateThrowEvent>')
    shape("Compensar", xt, yt - EV // 2, EV, EV, (xt - 40, yt - 70, 116, 40))
    nodos.append('<bpmn:endEvent id="FinCompensada" name="Saga compensada" />')
    shape("FinCompensada", xt + 100, yt - EV // 2, EV, EV, (xt + 80, yt + 24, 76, 27))
    flujos.append('<bpmn:sequenceFlow id="F_fin_comp" sourceRef="Compensar" targetRef="FinCompensada" />')
    edge("F_fin_comp", [(xt + EV, yt), (xt + 100, yt)])
    xs = 250
    for clave, *_ in PASOS:
        fid = f"FE_{clave}"
        flujos.append(f'<bpmn:sequenceFlow id="{fid}" sourceRef="E_{clave}" targetRef="Compensar" />')
        edge(fid, [(xs + 82, YC - H // 2 - EV // 2), (xs + 82, yt), (xt, yt)])
        xs += W + 70 + (EV + 70 if clave == "Cobro" and acreditacion else 0)

    # ids de entrada/salida en nodos
    xml_nodos = "\n    ".join(nodos + flujos + artefactos)  # el XSD pide artifacts al final
    msg = ""
    if acreditacion:
        msg = '<bpmn:message id="Msg_pago" name="pago-acreditado"><bpmn:extensionElements><zeebe:subscription correlationKey="=pedidoId" /></bpmn:extensionElements></bpmn:message>'
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" xmlns:di="http://www.omg.org/spec/DD/20100524/DI" xmlns:zeebe="http://camunda.org/schema/zeebe/1.0" xmlns:modeler="http://camunda.org/schema/modeler/1.0" id="Definitions_{pid}" targetNamespace="http://bpmn.io/schema/bpmn" modeler:executionPlatform="Camunda Cloud" modeler:executionPlatformVersion="8.9.0">
  {chr(10).join("  " + e for e in errores)}
  {msg}
  <bpmn:process id="{pid}" name="Compra (saga orquestada)" isExecutable="true">
    {xml_nodos}
  </bpmn:process>
  <bpmndi:BPMNDiagram id="Diagram_{pid}">
    <bpmndi:BPMNPlane id="Plane_{pid}" bpmnElement="{pid}">
      {chr(10).join("      " + s for s in shapes).strip()}
      {chr(10).join("      " + s for s in edges).strip()}
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>
'''


if __name__ == "__main__":
    d = Path(__file__).parent
    (d / "compra.bpmn").write_text(generar(False))
    (d / "compra-con-acreditacion.bpmn").write_text(generar(True))
    print("OK: compra.bpmn, compra-con-acreditacion.bpmn")
