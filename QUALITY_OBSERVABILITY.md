# QUALITY_OBSERVABILITY.md — Fase 8: Calidad, testing y observabilidad

> Basado en todas las fases anteriores, en particular [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md)
> (Fase 4, donde nació `in_agent_executions`) y [ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md)
> (Fase 0, que marcó "sin observabilidad" y "sin tests HTTP" como brechas reales). Implementada de
> punta a punta. **116/116 tests de backend** (100 antes de esta fase + 16 nuevos), verificado en
> vivo. Esta fase, como la 6 y la 7, encontró un defecto real de producción durante su propia
> verificación — esta vez, gracias a un test end-to-end genuino, no a una prueba manual (§1).

## 1. Estrategia de testing

**Lo que ya existía** (Fases 0-7): unitarios (ingesta, dominio, tools), de agente (grafo completo
con LLM stubbeado, contra datos mock y contra el Excel real), de generación de documentos (docx +
PDF real), y HTTP parciales (generación determinística, reconstrucción de historial).

**Lo que esta fase cierra:**

- **CRUD de conversaciones a nivel HTTP** (`test_conversations_api.py`): renombrar, anclar/
  desanclar (con verificación real de que anclar reordena la lista, no solo que el flag cambia),
  eliminar, y los 404 correspondientes — ninguno tenía prueba HTTP antes de esta fase.
- **Un test "golden path" end-to-end genuino**: encadena generar (HTTP real) → renombrar → anclar
  → verificar orden → descargar (archivo real) → eliminar, contra la API completa con generación de
  documento real. Es lo más cerca que esta suite llega de un E2E de navegador sin introducir
  herramientas nuevas (Playwright) — ver §6 sobre esa decisión.
- **`cost_estimation.py`** y las columnas nuevas de `in_agent_executions` (tokens, costo,
  `triggered_by`).
- **El fake de Supabase usado en tests ahora respeta `order`/`limit`** (antes los ignoraba
  silenciosamente) — sin esto, el test de "anclar reordena la lista" no podía existir de verdad, y
  cualquier lógica futura que dependa de orden/límite quedaría sin cobertura real.

**El hallazgo del test golden-path — un bug real, no solo un ejercicio de cobertura:**
`ConversationService.delete_conversation()` llamaba `checkpointer.adelete_thread(id)` directamente.
`AsyncSqliteSaver` crea sus tablas (`checkpoints`, `writes`) de forma perezosa, la primera vez que
se **escribe** un checkpoint real — pero `adelete_thread()` no lo sabe, y ejecuta un `DELETE FROM
checkpoints` asumiendo que la tabla ya existe. El test golden-path fue el primero en esta suite en
crear una conversación **puramente por el flujo determinístico** (que nunca toca el grafo de
LangGraph) en una base de datos de checkpoints **completamente nueva**, y luego borrarla — la
combinación exacta que dispara `sqlite3.OperationalError: no such table: checkpoints`. En este
mismo entorno de desarrollo el bug llevaba invisible desde la Fase 4 (el chat ya había creado esas
tablas hace mucho), pero en un despliegue nuevo, el primer usuario que genera un informe por
formulario y luego lo borra sin haber usado el chat antes se habría encontrado un 500. Corregido
llamando `await self._graph.checkpointer.setup()` (idempotente) antes de `adelete_thread()`.

## 2. Estrategia de evaluación del agente ("Validación de IA")

El groundedness eval de TruLens (`backend/evals/trulens_groundedness_eval.py`) existía desde antes
de esta fase pero **nunca había terminado de correr** — se estrellaba en su llamada al juez con
`Messages.create() got an unexpected keyword argument 'temperature'`. Esta fase lo diagnosticó a
fondo y lo dejó funcionando con resultados reales, en vez de dejarlo como trabajo abandonado.

**Diagnóstico real (no supuesto):** no es un problema del modelo elegido como juez — es que
`anthropic-python==1.5.0` (instalado en `.venv-eval`) **eliminó `temperature` y `reasoning_effort`
del método tipado `messages.create()` por completo** (verificado con `inspect.signature`, no
documentación). El proveedor de Anthropic de TruLens 2.14.0 siempre inyecta uno de los dos según si
clasifica el modelo juez como "modelo de razonamiento" — no existe ninguna elección de modelo que
evite el problema, porque el código lo agrega incondicionalmente.

**Corrección:** un parche mínimo y documentado en el propio script del eval (no en el paquete
instalado) que (a) fuerza `_is_reasoning_model()` a `True` para evitar la inyección de
`temperature`, y (b) intercepta `_create_chat_completion` para descartar `reasoning_effort` antes
de la llamada real al SDK. Verificado primero de forma aislada contra la API real antes de
integrarlo al script completo — mismo principio de "verificar contra la API real, no asumir" que ya
guía este proyecto.

**Resultados reales, primera corrida exitosa:**

| Escenario | Groundedness |
|---|---|
| `informe_general` | **0.981** |
| `enfoque_agente_desconectado` | *(sin resultado — ver nota)* |
| `solo_criticas_y_altas` | **1.000** |

Ambos escenarios con resultado dieron una narrativa altamente fundamentada en los datos reales. El
escenario `enfoque_agente_desconectado` no produjo un score numérico — el log muestra una
advertencia de TruLens ("Failed to process and remove trivial statements") sugiriendo que, para ese
filtro específico (una sola categoría), la narrativa fue lo bastante corta como para que el paso
interno de "remover afirmaciones triviales" del juez la dejara sin nada que puntuar. **No se
investigó más a fondo dentro de esta fase** (es un detalle del juez, no evidencia de que la
narrativa en sí sea menos fundamentada) — se documenta como recomendación de monitoreo (§5): si
persiste en corridas futuras, vale la pena revisar el prompt de `groundedness_measure_with_cot_reasons`
para respuestas cortas.

**Complementa, no reemplaza**, la validación determinista que ya existe en cada informe real
(`ReportSpecification.validate_evidence`, Fase 4/6) — ese chequeo sigue siendo el que bloquea la
generación de un informe con una cita fabricada; el eval de TruLens mide algo más sutil (una cita
real pero interpretada de forma que los datos no sostienen), y corre offline, no en el camino
crítico de producción.

## 3. Métricas — qué se captura ahora en `in_agent_executions`

| Campo | Desde | Qué responde |
|---|---|---|
| `duration_ms` | Fase 4 | ¿Cuánto tardó esta ejecución? |
| `status`, `error_messages` | Fase 4 | ¿Terminó bien? ¿Con qué error si no? |
| `model` | Fase 4 | ¿Qué modelo generó este informe? |
| **`usage_metadata`** | **Fase 8** | ¿Cuántos tokens de entrada/salida consumió, por modelo? |
| **`estimated_cost_usd`** | **Fase 8** | ¿Cuánto costó esta ejecución, aproximadamente? |
| **`triggered_by`** | **Fase 8** | ¿Qué usuario la disparó? |

**Cómo se captura tokens sin tocar cada nodo:** en vez de modificar `understand_request`,
`generate_narrative` y las múltiples llamadas de `answer_question` una por una, se envuelve **toda
la ejecución** (la llamada completa al grafo, o al pipeline determinístico) en
`langchain_core.callbacks.get_usage_metadata_callback()` — un context manager que agrega
transparentemente el `usage_metadata` de cada `AIMessage` generado dentro del bloque, sin importar
cuántas llamadas al modelo ocurran ni en qué nodo. Verificado en vivo: un informe real reportó
8 011 tokens de entrada / 2 623 de salida / **US$0.063378** estimados — cifra que coincide
exactamente con la tarifa configurada ($3/$15 por millón).

**Costos — deliberadamente aproximados**: `app/services/report/cost_estimation.py` tiene una tabla
de tarifas USD/millón de tokens por modelo, con un comentario explícito de que son una foto
aproximada a verificar contra el pricing publicado de Anthropic antes de usarse para presupuesto
real — nunca inventa un costo para un modelo que no reconoce (devuelve `None`, no un número
adivinado).

## 4. Logs

Sin cambios de infraestructura — el proyecto sigue usando el logging estándar de `uvicorn`/Python
(`logger.warning(...)` ya usado desde la Fase 3 para fallos best-effort de ingesta/auditoría). No
se introdujo un sistema de logging estructurado (ej. `structlog`, exportación a un colector externo)
— evaluado y pospuesto deliberadamente: con el volumen actual (una instalación, sin tráfico
concurrente real) los logs de proceso ya son suficientes para depurar, y `in_agent_executions` ya
cubre la trazabilidad estructurada que de verdad importa (qué pasó, cuándo, con qué datos, a qué
costo) sin necesitar parsear texto de log. Se recomienda revisar esto si el proyecto pasa a
producción con múltiples instancias (§5).

## 5. Auditoría — las preguntas del prompt maestro, respondidas contra el esquema real

| Pregunta | Respuesta hoy |
|---|---|
| ¿Qué datos utilizó este informe? | `in_agent_executions.request_params` (parámetros exactos) + `in_report_versions.specification_json` (contenido final, con cada cita verificada contra `alarm_number`s reales) |
| ¿Qué usuario lo generó? | `in_agent_executions.triggered_by` → `in_users` (**nuevo esta fase** — antes siempre `null`) |
| ¿Qué modelo se utilizó? | `in_agent_executions.model` (Fase 4) |
| ¿Qué herramientas fueron invocadas? | Para `answer_question`: no quedan registradas individualmente (fuera de alcance de esta fase — ver Recomendaciones). Para el pipeline de generación: implícito en `mode` + los pasos fijos de cada modalidad, documentados en AGENT_ARCHITECTURE.md/DETERMINISTIC_FLOW.md |
| ¿Cuándo fue generado? | `started_at`/`completed_at` (Fase 4) |
| ¿Qué versión del sistema existía? | **No respondible hoy** — el proyecto no es un repositorio git (riesgo "Alto" ya señalado en la Fase 0, sin resolver). Sin control de versiones no hay un identificador de versión que grabar. Se recomienda como el ítem de mayor prioridad para la Fase 9. |

## 6. Recomendaciones de monitoreo

1. **Inicializar control de versiones** (repetido desde la Fase 0 — sigue siendo la recomendación
   de mayor prioridad, y ahora tiene una consecuencia concreta y nombrada: sin git, la pregunta de
   auditoría "¿qué versión generó este informe?" no tiene respuesta posible).
2. **Revisar el escenario sin score del eval de TruLens** si se repite en corridas futuras (§2) —
   podría ser una señal real de narrativas demasiado cortas para el filtro de "afirmaciones
   triviales" del juez, o solo una particularidad de ese escenario puntual.
3. **Registrar qué herramientas invoca `answer_question` por ejecución** (hoy no se registra
   individualmente) si el volumen de preguntas puntuales crece lo suficiente como para que valga la
   pena auditar patrones de uso de herramientas, no solo el resultado final.
4. **E2E de navegador (Playwright) — evaluado y pospuesto, no descartado.** El test "golden path"
   de esta fase ya cubre el mismo recorrido a nivel de API+generación real; lo único que no prueba
   es la capa de DOM/JS del frontend. Se pospone porque: (a) no había ninguna herramienta de
   automatización de navegador en el proyecto todavía, y agregarla es una decisión de tooling con
   costo de mantenimiento propio: (b) cada fase de este proceso ya incluyó verificación manual real
   en navegador (capturas, interacción real) que cubrió ese mismo terreno bajo demanda. Vale la
   pena revisarlo si el equipo crece más allá de quien puede verificar manualmente cada cambio.
5. **Logging estructurado / colector externo** — solo si el despliegue pasa a producción real con
   múltiples instancias (§4); no está justificado al volumen actual.

---

**Fin de la Fase 8.** Backend: 116/116 tests. Frontend: sin cambios esta fase, `tsc --noEmit` limpio,
4/4 tests. Quedo a la espera de tu aprobación para iniciar la Fase 9 (seguridad y preparación para
producción) — que, dado lo encontrado en esta fase, debería tratar la inicialización de git como
parte explícita de su alcance.
