# Demo: saga de compra orquestada con Camunda 8

Una compra de 4 pasos (crear orden → reservar stock → cobrar → programar envío) definida en **un solo
diagrama BPMN** y ejecutada por Camunda. Cada paso lo hace un **worker** (servicio) independiente, que
puede correr en otra laptop y solo habla con el orquestador.

## Qué muestra

- **Orquestación:** el proceso completo está en un lugar (`bpmn/compra.bpmn`). Los servicios no se conocen entre sí.
- **Compensación:** si un paso falla por una razón de negocio, se deshacen los pasos anteriores en orden
  inverso (una saga no es atómica: no hay rollback, hay acciones inversas).
- **Durabilidad:** si un servicio se cae, la instancia queda esperando y sigue cuando vuelve.
- **Error de negocio vs. falla técnica:** el primero compensa; la segunda reintenta y, si se agotan, abre un incidente.

## Qué hace Camunda y qué hacemos nosotros

| Camunda | Nosotros |
|---|---|
| Recorre el diagrama y guarda el estado de cada instancia | El diagrama: pasos, errores y qué compensa a cada paso |
| Reparte jobs a los workers, aplica timeouts y reintentos (3) | Los 4 workers: la lógica de negocio y su estado propio |
| Dispara las compensaciones en orden inverso (solo de lo ya completado) | El código de las compensaciones (cancelar, liberar, reembolsar) |
| Crea incidentes, muestra todo en Operate | La **idempotencia**: Camunda entrega un job *al menos una vez*, el worker evita repetir el efecto |

| Paso | Job | Compensación | Servicio |
|---|---|---|---|
| Crear orden | `crear-orden` | `cancelar-orden` | ordenes |
| Reservar stock | `reservar-stock` | `liberar-stock` | inventario |
| Cobrar | `cobrar` | `reembolsar` | pagos |
| Programar envío | `programar-envio` | — | envios |

## Correr todo en una máquina (tmux)

Requisitos: Docker + Compose, tmux, Python 3.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # una sola vez
scripts/tmux-demo.sh
```

El script levanta Camunda (la primera vez tarda ~1 min), abre Operate en el navegador
(<http://localhost:8080/operate>, usuario `demo`, contraseña `demo`) y crea una sesión de tmux con pestañas:

| Pestaña | Qué es |
|---|---|
| `1 comandos` | terminal donde se lanzan las instancias (`iniciar ...`) |
| `2 ordenes` · `3 inventario` · `4 pagos` · `5 envios` | un worker por pestaña, con sus logs |
| `6 camunda` | logs del orquestador |

Moverse: `Ctrl+b 1..6`, `Ctrl+b n/p`, o clic en la barra. Salir sin cerrar: `Ctrl+b d`.
Cerrar la sesión: `scripts/tmux-demo.sh stop` (Camunda sigue corriendo; se apaga con `cd orquestador && docker compose down`).

## Escenarios (en la pestaña `1 comandos`)

```
iniciar feliz                 # todo sale bien
iniciar falla-envio           # falla el envío -> reembolsa, libera stock, cancela orden
iniciar falla-cobro           # pago rechazado -> libera stock, cancela orden
iniciar falla-stock           # sin stock -> cancela orden
iniciar falla-tecnica-cobro   # falla técnica -> 3 reintentos -> incidente
iniciar duplicado             # el mismo job llega dos veces -> no se repite el efecto
iniciar lote 5                # 5 compras felices seguidas
```

En Operate: *Processes* → *Compra (saga orquestada)* → abrir una instancia → *Instance History*.

## Guion de la demo (5–7 min)

1. **Diagrama:** mostrarlo en Operate. "El proceso completo está en un solo lugar."
2. **Camino feliz:** `iniciar feliz`. Ver la instancia avanzar y los logs de cada servicio (`Stock: 10 -> 9`).
3. **Compensación:** `iniciar falla-envio`. En Operate se ve reembolso → liberar stock → cancelar orden,
   y termina en "Saga compensada". En `3 inventario`, el stock vuelve a su valor.
4. **Durabilidad:** en `4 pagos`, `Ctrl+C`. En `1 comandos`, `iniciar feliz`: la instancia queda esperando en
   "Cobrar". Volver a `4 pagos` y apretar Enter: el worker vuelve y la instancia termina.
5. **Falla técnica (opcional):** `iniciar falla-tecnica-cobro`. Pagos falla 3 veces y aparece un incidente en
   "Cobrar". Resolverlo desde Operate (pestaña *Incidents*, botón de reintento); la saga continúa. No se compensó
   nada: una falla técnica no es una decisión de negocio.

## Varias laptops

Un solo cambio: los workers apuntan al orquestador por red.

1. **Orquestadora:** `cd orquestador && docker compose up -d`. Obtener su IP: `hostname -I` (Linux),
   `ipconfig getifaddr en0` (macOS) o `ipconfig` (Windows). Abrir el puerto **TCP 26500** en el firewall
   (`sudo ufw allow 26500/tcp`).
2. **Probar desde la otra laptop:** `nc -zv <IP> 26500` debe responder "succeeded".
3. **Cada laptop de worker:** clonar el repo, crear el venv (como arriba) y
   ```bash
   cp .env.example .env     # editar: ZEEBE_ADDRESS=<IP>:26500 y WORKER_NAME=laptop-<nombre>
   .venv/bin/python workers/pagos/main.py     # ordenes | inventario | pagos | envios
   ```
4. **Lanzar instancias** desde cualquier máquina con el mismo `.env`: `scripts/iniciar feliz`.

Si la red del aula aísla los dispositivos (la prueba de `nc` falla), usar el modo de una sola máquina o un hotspot.

## Extensión: evento externo

`bpmn/compra-con-acreditacion.bpmn` agrega, tras *Cobrar*, un evento "Pago acreditado" que espera un mensaje
externo (simula el webhook del banco), correlacionado por `pedidoId`.

```bash
scripts/iniciar --con-acreditacion feliz                    # queda esperando en "Pago acreditado"
scripts/iniciar --con-acreditacion acreditar <pedidoId>     # publica el mensaje y continúa
```

## Detalles

- **Versiones:** Camunda 8.9.22 (Zeebe + Operate + Tasklist, compose oficial reducido), pyzeebe 4.7.0, Python 3.12.
- **Autenticación:** la UI usa `demo/demo`; la API gRPC del compose no pide credenciales (solo desarrollo local).
  Para un cluster con OAuth, definir `ZEEBE_CLIENT_ID`, `ZEEBE_CLIENT_SECRET` y `ZEEBE_AUTHORIZATION_SERVER_URL`.
- **Workers:** estado propio en memoria (se reinicia al reiniciar el worker), 1–2 s de trabajo simulado, job
  timeout de 25 s, idempotencia por `(job, pedidoId)`. Variables opcionales: `JOB_TIMEOUT_MS`, `FALLAS_TECNICAS`.
- **Falla técnica simulada:** ocurre las primeras 3 veces por pedido, así el reintento desde Operate ya funciona.
- **Modo sin tmux:** `scripts/levantar-todos.sh` levanta los 4 workers en una terminal.
- **BPMN:** `python3 bpmn/generar.py` regenera los `.bpmn`; también se editan con Camunda Modeler. Los
  `compensateEventDefinition` necesitan `id` o el deploy falla con un error poco claro.
- **No verificado:** el botón de reintento de incidentes en la UI de Operate (probé la resolución por API) y la
  conectividad entre laptops reales.

```
orquestador/docker-compose.yaml    bpmn/compra.bpmn            workers/{comun,ordenes,inventario,pagos,envios}
scripts/{tmux-demo.sh,iniciar,iniciar.py,levantar-todos.sh}    .env.example
```
