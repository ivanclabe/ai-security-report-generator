# CONVERSATIONAL_EXPERIENCE.md — Fase 6: Mejora de la experiencia conversacional

> Basado en [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md) (Fase 4) y
> [DETERMINISTIC_FLOW.md](DETERMINISTIC_FLOW.md) (Fase 5). Implementada de punta a punta.
> 94/94 tests de backend (87 antes de esta fase + 7 nuevos), frontend sin errores de tipos.
> Esta fase encontró y corrigió, además, un defecto real de fiabilidad descubierto durante la
> propia verificación en vivo (§5).

## 0. Punto de partida: qué ya cumplía cada requisito antes de esta fase

Antes de tocar código se revisó cada capacidad que el prompt maestro pide contra lo ya construido
en las Fases 4-5, para no reconstruir lo que ya funciona:

| Capacidad pedida | Estado antes de esta fase |
|---|---|
| Solicitar informes | ✅ Ya existía |
| Filtrar alertas | ✅ Ya existía (`focus_categories`/`risk_level_filter`) |
| Solicitar explicaciones | ✅ Ya existía (`answer_question`, Fase 4) |
| Cambiar nivel de detalle | ✅ Ya existía (`audience`) |
| Solicitar un documento | ✅ Ya existía |
| Persistir conversaciones/mensajes | ✅ Ya existía (Supabase) |
| Mantener contexto | ✅ Ya existía (checkpointer LangGraph) |
| Identificar intención | ✅ Ya existía (`ReportRequestUpdate.intent`) |
| Detectar parámetros faltantes | ✅ Ya existía (`missing_info_question`) |
| Sugerencias iniciales / ejemplos | ✅ Ya existía (`SUGGESTED_PROMPTS`) |
| Estado de generación | ✅ Ya existía (`ProgressStatus`) |
| Historial de conversaciones | ✅ Ya existía (Sidebar) |
| Botones de descarga | ✅ Ya existía (`ReportCard`) |
| Integración sin duplicar lógica | ✅ Ya cumplido desde la Fase 4 (`app/services/report/*`) |
| **Analizar tendencias** | ⚠️ Los datos existían (`get_alert_trends`) pero `answer_question` no tenía forma de usarlos |
| **Regenerar secciones** | ⚠️ Solo "regenerar todo el informe" (modify_report) — sin regeneración granular |
| **Descargar informes previamente generados** | ❌ Roto: la tarjeta de descarga no se reconstruía al reabrir una conversación |
| **Quick actions** | ❌ No existían — solo sugerencias en el estado vacío |
| **Preview del informe** | ❌ La tarjeta solo mostraba título/versión/cantidad de secciones |
| Confirmar acciones importantes | Evaluado y descartado deliberadamente (§4) |

Esta fase se enfocó exclusivamente en las filas marcadas ⚠️/❌ — el resto ya cumplía el requisito y
tocarlo habría sido reescribir sin necesidad.

## 1. Flujo UX

```mermaid
flowchart TB
    A["Usuario genera un informe\n(chat o formulario)"] --> B["ReportCard: título, preview\ndel objetivo, botón de descarga"]
    B --> C{"¿Qué hace el usuario después?"}
    C -->|"Click en quick action"| D["Mensaje pre-armado enviado\n(Hazlo más ejecutivo / técnico /\nAnaliza tendencias / Compara período)"]
    C -->|"Escribe pregunta libre"| E["understand_request clasifica intent"]
    C -->|"Recarga la página / reabre\nla conversación desde el Sidebar"| F["GET /api/conversations/{id}\nreconstruye el mismo ReportCard"]
    D --> E
    E -->|intent=question| G["answer_question\n(tool-calling acotado:\nalarma puntual, búsqueda, TENDENCIAS)"]
    E -->|intent=modify_report| H["Pipeline completo\n(mismo de Fase 4/5)"]
    G --> I["Respuesta grounded,\nsin regenerar el informe"]
    H --> B
```

## 2. Arquitectura de interacción

Ningún cambio estructural al grafo de la Fase 4 — el enrutamiento (`understand_request` →
`answer_question` | `collect_data` | `ask_user`) ya era el mecanismo correcto. Esta fase extiende
lo que `answer_question` puede hacer y arregla cómo el frontend reconstruye lo que el backend ya
tenía disponible:

- **`analizar_tendencia`** (nueva, tercera tool de `answer_question`): envuelve
  `security_tools.get_alert_trends` (ya existente, ya probado) — sin código nuevo de análisis, solo
  el punto de conexión que faltaba. Acotada igual que las otras dos: solo lectura, sin fecha fuera
  del período del informe activo salvo que el usuario la pida explícitamente.
- **Quick actions** (`ReportCard.tsx`): chips que llaman a `sendUserMessage` con un prompt
  pre-armado — reutilizan exactamente el mismo camino que si el usuario los hubiera escrito a mano,
  cero lógica nueva de backend. Se desactivan en la vista de Formulario (`showQuickActions={false}`)
  porque ahí no hay una vista de chat visible a la que "aterrice" la respuesta.
- **Preview del informe**: el campo `objective` (ya calculado por la narrativa del LLM) ahora viaja
  en el payload `report` que ya existía (`ReportOut`) — sin cálculo nuevo, solo se dejó de
  descartar un dato que ya se tenía.
- **Reconstrucción de la tarjeta de descarga**: `GET /api/conversations/{id}` ahora arma el mismo
  objeto `report` que ya se construye en vivo (`ConversationService.get_report_card_for_conversation`,
  reutiliza `ReportRepository.get_latest_version`) y el frontend lo adjunta al último mensaje del
  asistente (`useConversationStore.selectConversation`) — mismo mecanismo de render que ya usa
  `MessageBubble`, sin componente nuevo.

## 3. Casos de uso (verificados en vivo, no solo diseñados)

1. **Generar informe → pedir tendencias por chip.** Se generó un informe real de THOMAS TGS-TPS en
   el navegador, se hizo clic en "Analiza las tendencias de este período", y `answer_question`
   respondió con un desglose semanal real (W27-W31, total y alarmas críticas, con cifras exactas
   calculadas por `get_alert_trends` contra los datos reales) — sin regenerar el informe.
2. **Recargar la página tras generar un informe.** La tarjeta de descarga (con preview y quick
   actions) reaparece idéntica a como se veía en vivo — antes de esta fase, desaparecía por
   completo.
3. **Generar por formulario, luego seguir la conversación por chat.** Ya funcionaba desde la
   Fase 5 (la generación por formulario crea una conversación real); esta fase no lo modifica pero
   se revalidó que sigue funcionando con los cambios nuevos.

## 4. Manejo de contexto

Sin cambios respecto a la Fase 4 — el checkpointer de LangGraph sigue siendo el único mecanismo de
memoria, y `answer_question` sigue beneficiándose de él sin trabajo adicional. Se evaluó
explícitamente **"confirmar acciones importantes"** (pedido por el prompt maestro) y se decidió
**no** agregar un paso de confirmación: cada regeneración crea una versión nueva en
`in_report_versions` sin destruir ninguna anterior, así que no hay ninguna acción "importante" en
el sentido de irreversible — agregar fricción de confirmación no reduciría ningún riesgo real, solo
ralentizaría el flujo. Se documenta la decisión en vez de construir una UI de confirmación sin un
riesgo concreto que mitigar.

## 5. Manejo de errores — el hallazgo real de esta fase

Durante la verificación en vivo del chip "Analiza las tendencias", la respuesta mostrada al usuario
incluyó, pegado al final del texto, literalmente esto:

```
...seguido de una desescalada notable en la última semana del mes.</answer>
<parameter name="cited_alarm_numbers">[]
```

**Diagnóstico:** `with_structured_output` (método `function_calling`) de `ChatAnthropic`, al
producir un campo de texto largo dentro de una tool-call forzada, en aproximadamente 1 de cada 6-8
llamadas reales, filtra una re-serialización mal formada de su propio schema al final del string —
usando los nombres reales de los campos del schema (`answer`, `cited_alarm_numbers`), lo que sugiere
que es un artefacto del propio modelo, no un error de parseo de LangChain. Se descartó como causa
una hipótesis inicial (reenviar el historial crudo de `tool_use`/`tool_result` a una llamada con
herramientas distintas) — corregirla no eliminó el problema, confirmando que es ruido del modelo,
no un error de nuestro código armando mal los mensajes.

**Corrección aplicada — dos capas, igual que el resto del sistema hace con ruido del modelo:**

1. **Preventiva:** se dejó de reenviar los mensajes crudos con bloques `tool_use` a la llamada de
   salida estructurada — en su lugar, se construye un transcript de texto plano de lo que cada
   herramienta devolvió. Reduce la superficie de confusión aunque no elimina el problema por sí
   sola.
2. **Defensiva (la que realmente lo resuelve):** un `field_validator` en `AnswerWithEvidence.answer`
   que trunca el string en el primer marcador de fuga conocido (`</answer>`,
   `<parameter name="cited_alarm_numbers"`) — exactamente el mismo patrón ya usado en
   `ReportNarrative` (`_coerce_string_to_list`/`_coerce_string_to_recommendation`, Fase previa a
   esta) para tolerar salidas mal formadas del modelo sin fallar ni mostrar basura al usuario.
   Verificado con 8 llamadas reales adicionales tras la corrección: ninguna mostró el artefacto en
   el mensaje final al usuario.

Este hallazgo refuerza, con un ejemplo concreto y nuevo, el principio ya establecido en
`AGENT_ARCHITECTURE.md`: nunca confiar en texto libre del modelo sin una capa de validación
programática — aquí no se trataba de una alucinación de datos (la información era correcta), sino
de un defecto de formato, y el mismo principio de "nunca confiar ciegamente" lo atrapó igual.

## 6. Estrategia de persistencia

Sin tablas nuevas. El único cambio de esquema es a nivel de respuesta HTTP:
`ConversationDetail.report` (nuevo campo, `ReportOut | None`) y `ReportOut.objective` (nuevo campo)
— ambos aditivos, no rompen ningún cliente que no los use. `ReportRepository.get_for_conversation`
(nuevo método, solo lectura) se agregó junto a `get_or_create_for_conversation` (ya existente,
usado para escritura) para no crear accidentalmente una fila `in_reports` vacía al solo querer leer.

## 7. Pruebas

- **`test_answer_question.py`**: +3 tests para la tool de tendencias (incluye el guard de
  "sin empresa/período activo") y +3 tests de regresión para el saneo de la fuga de sintaxis
  (incluye el caso límite: si el string entero fuera basura, no se muestra un mensaje vacío).
- **`test_conversations_api.py`** (nuevo archivo): confirma que una conversación sin informe
  devuelve `report: null`, y que reabrir una conversación con informe reconstruye exactamente los
  mismos datos que se vieron en vivo.
- **Refactor de test fixtures**: el `FakeSupabase`/`TestClient` que antes vivía duplicado en
  `test_reports_api.py` se extrajo a `conftest.py` (`fake_supabase`, `api_client`, `auth_headers`,
  `parse_sse_events`) — se usa ahora en dos archivos de test y evita divergencia entre copias.
- **Verificado en vivo** en el navegador real: generación de informe, preview visible, quick
  actions visibles y funcionales, respuesta de tendencias con datos reales, y reconstrucción de la
  tarjeta tras recargar la página — con limpieza de las conversaciones de prueba al finalizar.

---

**Fin de la Fase 6.** Backend: 94/94 tests. Frontend: `tsc --noEmit` limpio, 4/4 tests. Quedo a la
espera de tu aprobación para iniciar la Fase 7 (generación profesional de DOCX y PDF).
