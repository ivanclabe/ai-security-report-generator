# FINAL_ARCHITECTURE.md — Fase 10: Integración final y documentación

> Documento capstone: consolida las diez fases del prompt maestro
> ([ARCHITECTURE_ASSESSMENT.md](ARCHITECTURE_ASSESSMENT.md) →
> [SECURITY_REVIEW.md](SECURITY_REVIEW.md)) en una única referencia del estado final de la
> plataforma. No re-deriva las decisiones — las cita y remite al documento de fase
> correspondiente para el detalle y el razonamiento original.

## 1. Arquitectura final

Monolito modular con dos aplicaciones (backend FastAPI, frontend React) y un almacenamiento
externo (Supabase Postgres):

```
┌──────────────────────────── Frontend (React + TS + Vite) ────────────────────────────┐
│   Sidebar (conversaciones: crear/renombrar/anclar/eliminar)                           │
│   Tab "Formulario" (Modalidad 1: flujo determinístico) ──┐                            │
│   Tab "Chat" (Modalidad 2: flujo conversacional) ────────┼──► REST + SSE              │
└────────────────────────────────────────────────────────┬┴────────────────────────────┘
                                                           │
┌──────────────────────────────────────────────────────── ▼ ───────────────────────────┐
│  FastAPI backend                                                                       │
│                                                                                         │
│  app/api/          auth · conversations · reports · reference_data · health           │
│  app/agents/        LangGraph StateGraph (9 nodos) + AsyncSqliteSaver checkpointer      │
│  app/services/report/  collection · analysis · specification · validation · document · │
│                        execution_tracking · cost_estimation · pipeline (determinístico) │
│  app/tools/         security_tools.py -- tools tipadas (Pydantic) que el agente llama   │
│  app/providers/     DataProvider: excel (default) · mock · api (placeholder)            │
│  app/document/      python-docx builder + conversión a PDF (LibreOffice headless)       │
│  app/auth.py        JWT + rate limiter de login                                         │
└───────────────┬─────────────────────────────────────────────────────────┬─────────────┘
                │                                                         │
                ▼                                                         ▼
   Supabase Postgres (in_*)                                  SQLite local
   conversations, messages,                                  agent_checkpoints.sqlite3
   reports, report_versions,                                 (estado LangGraph por
   agent_executions                                           conversation_id)
```

Ambas modalidades del producto (formulario y chat) son *clientes delgados* de la misma capa de
servicios (`app/services/report/*`) — la decisión central de [ARCHITECTURE_TARGET.md](ARCHITECTURE_TARGET.md)
(Fase 1), implementada en [DETERMINISTIC_FLOW.md](DETERMINISTIC_FLOW.md) (Fase 3) y
[AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md) (Fase 4). Ninguna lógica de negocio vive
duplicada entre el pipeline determinístico y los nodos del grafo.

## 2. Componentes

| Componente | Rol | Fase de origen |
|---|---|---|
| `DataProvider` (excel/mock/api) | Abstrae la fuente de datos de alarmas; agente y tools nunca conocen el origen concreto | Preexistente (POC), extendido en Fase 2 |
| `security_tools.py` | Tools explícitas, tipadas con Pydantic, que delegan en `DataProvider` — ninguna ejecuta SQL/código arbitrario del LLM | Preexistente, endurecido en Fase 9 |
| LangGraph `StateGraph` (9 nodos) | Orquesta el flujo conversacional: entender petición → (recolectar → analizar → generar spec → validar → generar doc) \| responder pregunta | Refactorizado en Fase 4 |
| `answer_question` | Único nodo con tool-calling real (bucle acotado, `MAX_TOOL_ITERATIONS`); cada cita de alarma se verifica contra lo que las tools devolvieron ese turno | Fase 4, endurecido en Fase 6 |
| `app/services/report/*` | Capa de servicios compartida entre ambos flujos — collection, analysis, specification, validation, document, execution_tracking, cost_estimation | Fase 1 (diseño) → Fase 3/4 (implementación) |
| `pipeline.run_deterministic` | Ejecuta la misma capa de servicios en un orden fijo, sin LLM decidiendo el siguiente paso — reproducible dado el mismo input | Fase 3 |
| `templates.py` | Registro de templates de sección (hoy un único `csoc_mensual`); el LLM nunca decide la estructura, solo redacta prosa (`ReportNarrative`) para campos puntuales | Preexistente, formalizado en Fase 1 |
| `document.py` | `python-docx` construye el `.docx` desde la `ReportSpecification` validada; conversión a PDF vía LibreOffice headless | Preexistente (docx), PDF agregado en Fase 7 |
| `in_agent_executions` | Registro de auditoría por ejecución: modo, triggered_by, modelo, tokens, costo estimado, duración, `system_version`, errores | Fase 4 (creada) → Fase 8/9 (completada) |
| `auth.py` | JWT de sesión única + rate limiter de login (10 intentos/5 min, en memoria) | Preexistente (JWT), rate limiter en Fase 9 |
| Frontend (React/Zustand) | Sidebar de conversaciones, tab Formulario, tab Chat, SSE streaming de progreso | Preexistente, extendido en Fase 3 (Formulario) |

## 3. Flujos principales

### Flujo A — Determinístico (Modalidad 1, "Formulario")

`usuario selecciona empresa → selecciona período → configura informe → ejecuta generación →
sistema consulta datos → sistema analiza → sistema genera documento → sistema guarda informe →
usuario descarga`

`POST /api/reports/generate` → `pipeline.run_deterministic`: valida parámetros → `collect` →
`analyze` → `build_specification` → `validate` → `render` (docx o pdf) → guarda
`report`/`report_version` → registra la ejecución en `in_agent_executions` (modo
`deterministic`) → SSE de progreso hasta el resultado final. Verificado en vivo en esta fase
(empresa THOMAS TGS-TPS, julio 2026, salida PDF): 8 secciones, PDF de 13 páginas renderizado
correctamente, ejecución registrada con costo y duración reales. Ver
[DETERMINISTIC_FLOW.md](DETERMINISTIC_FLOW.md).

### Flujo B — Conversacional (Modalidad 2, "Chat")

`usuario inicia conversación → solicita informe → agente identifica parámetros → agente consulta
herramientas → agente analiza información → usuario solicita modificaciones → agente regenera
contenido → usuario solicita documento → sistema genera DOCX/PDF → sistema guarda historial`

`understand_request` (structured output) clasifica intención y extrae campos → si faltan
datos, pausa (`awaiting_user_input`) pidiendo la aclaración puntual → si hay suficiente
información, recolecta/analiza/genera solo lo que cambió (una modificación de tono no
re-consulta datos; una modificación de empresa/período/filtros sí) → cada regeneración crea una
nueva `report_version` → el historial completo persiste en Supabase y se reconstruye al recargar
la página (fix de Fase 6: el checkpointer de LangGraph guarda el *estado* del agente, no los
mensajes visibles al usuario — esos se reconstruyen desde `in_messages`). Preguntas sobre datos
ya discutidos se resuelven vía `answer_question` sin pasar por el pipeline de generación. Ver
[AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md) y [CONVERSATIONAL_EXPERIENCE.md](CONVERSATIONAL_EXPERIENCE.md).

Verificado en vivo en esta fase, en una sola conversación: informe nuevo (v1, docx) → "hazlo más
ejecutivo" (v2, misma data, narrativa regenerada) → "genera el documento en PDF" (v3, pdf) →
pregunta sobre técnicas MITRE ATT&CK (respondida honestamente como "no disponible en los datos",
sin inventar una cita) → reload de página → las 3 versiones y el historial completo se
reconstruyen intactos.

## 4. Decisiones técnicas

- **Capa de servicios compartida en vez de duplicar lógica por modalidad** — la razón de ser de
  la Fase 1; evita que el flujo determinístico y el conversacional diverjan silenciosamente.
- **Un único `StateGraph` sin supervisor/subagentes** — la complejidad real (recolectar,
  analizar, generar, validar) vive en nodos secuenciales con enrutamiento condicional simple
  (`intent` + `status`), no en una jerarquía de agentes; no hay evidencia de que el dominio la
  necesite.
- **Templates de sección fijos en código, prosa del LLM acotada a campos puntuales** — el LLM
  nunca decide qué secciones lleva el informe ni compone HTML/Markdown libre; reduce
  alucinación estructural a cero por construcción.
- **Validación anti-alucinación de citas en dos capas independientes** — `answer_question`
  verifica cada `alarm_number` citado contra las tools realmente invocadas ese turno;
  `ReportSpecification.validate_evidence` hace lo mismo para el documento final. Dos mecanismos
  separados para el mismo riesgo, en los dos únicos lugares donde el LLM puede citar evidencia.
- **`DataProvider` como único punto de acoplamiento a la fuente de datos** — permitió agregar PDF,
  el flujo determinístico y observabilidad sin tocar `excel.py`/`mock.py`, y deja `api.py` como
  placeholder concreto para cuando exista una API real del cliente.
- **LangGraph `AsyncSqliteSaver` para el checkpointer, Supabase para todo lo visible al
  usuario** — evita reinventar persistencia de estado de agente (ya resuelto por la librería)
  mientras mantiene conversaciones/informes en un store consultable y con RLS.
- **JWT + credencial única de operador en vez de Supabase Auth completo** — justificado mientras
  exista un solo usuario legítimo; documentado explícitamente como el primer punto a resolver si
  eso cambia (§2 de `SECURITY_REVIEW.md`).
- **Rate limiter de login en memoria, no distribuido** — correcto para una única réplica (el
  despliegue actual); documentado en `SECURITY_REVIEW.md` §7 como el primer ajuste necesario
  antes de escalar horizontalmente.
- **Selección de lint deliberadamente angosta en esta fase (`E9,F,I` en vez del set completo de
  ruff)** — sintaxis, pyflakes e imports desordenados son señales de alta confianza y bajo
  ruido; reglas de estilo más amplias se dejan fuera para no generar un diff masivo de
  reformateo sin valor de corrección, siguiendo "no introduzcas cambios innecesarios".

## 5. Limitaciones conocidas

Todas documentadas con severidad y mitigación propuesta en [SECURITY_REVIEW.md](SECURITY_REVIEW.md)
(Fase 9, §1-§7); resumen:

| Limitación | Impacto | Mitigación propuesta |
|---|---|---|
| Sin autorización por organización/cliente — un solo operador ve todo | Alto si se agregan analistas de distintos clientes | Autorización real por organización antes de abrir acceso a más de un usuario (§2) |
| Documentos generados viven en disco local (`generated_reports/`), no en Supabase Storage | Medio — no sobrevive a un redeploy sin volumen persistente, no escala a múltiples réplicas | Migrar a Supabase Storage, ya diseñado desde Fase 1/2, nunca implementado (§3/§4) |
| Rate limiter de `/login` en memoria, no compartido entre réplicas | Bajo con una réplica; alto si se escala horizontalmente | Mover a almacén compartido (Redis u otro) (§7) |
| Sin rate limiting en `/api/reports/generate` | Medio — cada generación real cuesta tokens/LLM | Extender el mecanismo ya construido para `/login` (§6) |
| Sin política de retención de datos definida | Alto una vez existan datos sensibles reales (no sintéticos) | Requiere decisión de negocio antes de código (§3) |
| `report_type` como concepto de selección de template es en gran parte vestigial (un solo template registrado: `csoc_mensual`) | Bajo — corregido en esta fase (ver Fase 10, hallazgo en vivo abajo) | Si se agregan templates reales, revisar que el campo siga bien acotado para el LLM |
| Vulnerabilidades moderadas/altas en dependencias de desarrollo del frontend (`vite`/`esbuild`/`vitest`, servidor de dev únicamente) | Bajo — no afecta el build de producción ni el runtime servido | `npm audit fix --force` implica subir `vitest` a una versión mayor (breaking); evaluar en una fase de mantenimiento dedicada |
| Sin MFA / gestión de usuarios real | Medio, junto con el punto de autorización | Cuando exista más de un usuario legítimo (§9.5) |

## 6. Hallazgo en vivo de esta fase (Fase 10)

La validación en vivo del Flujo B encontró un defecto real: pedir "hazlo más ejecutivo" sobre un
informe ya generado fallaba con `Unknown report template: executive`. Causa raíz: el campo
`ReportRequestUpdate.report_type` (visto por el LLM vía `with_structured_output`) tenía una
descripción que invitaba a valores como `"executive"`, pero el registro de templates
(`templates.py`) solo tiene una clave real (`csoc_mensual`) — el mecanismo correcto para
tono/enfoque ("más ejecutivo", "más técnico") es el campo `audience`, ya conectado a
`generate_narrative`. Corregido ajustando las descripciones de ambos campos en
`app/agents/state.py` para que el LLM deje de inventar valores de `report_type` y use `audience`
para ese caso; verificado en vivo tras el fix (misma solicitud, misma conversación fresca,
resultado correcto: v2 con narrativa ejecutiva). Ningún test existente cubría este flujo
específico contra el registro real de templates — los 129 tests de backend siguen en verde tras
el fix. Patrón consistente con lo observado en Fases 5-9: la verificación en vivo contra
servicios reales sigue encontrando defectos que las pruebas unitarias con LLM stubbeado no
pueden, por construcción, detectar.

## 7. Roadmap futuro

En orden sugerido (ver también `SECURITY_REVIEW.md` §9):

1. **Autorización por organización/cliente** — el ítem de mayor impacto, bloqueado detrás de una
   decisión de negocio (¿habrá más de un operador? ¿más de un cliente final visible a la vez?).
2. **Migrar documentos generados a Supabase Storage** — elimina la dependencia de disco local y
   habilita múltiples réplicas del backend.
3. **Rate limiting en `/api/reports/generate`** — extensión directa del mecanismo de `/login`.
4. **Política de retención de datos** — antes de manejar datos sensibles reales.
5. **MFA / gestión de usuarios real** — junto con el punto 1.
6. **Rate limiter distribuido** — solo si se despliega en más de una réplica.
7. **Segundo template de informe** — hoy el registro (`templates.py`) soporta múltiples templates
   por diseño pero solo uno existe; agregar el segundo real validará que la abstracción
   (`register_template`) generaliza correctamente en la práctica, no solo en el papel.

## 8. Próximas integraciones de API

`ApiDataProvider` (`backend/app/providers/api.py`) ya implementa el contrato `DataProvider`
completo con `NotImplementedError` explícitos por método — es el punto de extensión concreto,
no un diseño pendiente. Cuando el cliente exponga una API real de datos de seguridad:

1. Implementar cada método usando `httpx` (ya es dependencia) contra el endpoint real.
2. Mapear la respuesta JSON a los modelos de dominio (`app/models/domain.py`) con el mismo rigor
   de validación que `excel_ingestion.py` aplica hoy (campos requeridos, fechas, duplicados).
3. Reusar `ingestion_service.py` para registrar metadata de importación — su contrato
   (`data_source_id`, hash/marca de sincronización, warnings) ya es agnóstico de si el origen
   fue un archivo o una respuesta HTTP.
4. Activar con `DATA_PROVIDER=api` — nada en el agente, las tools, o el pipeline determinístico
   necesita cambiar.

Ver también `INGESTION_ARCHITECTURE.md` (Fase 2) para el diseño original de este punto de
extensión.

## 9. Recomendaciones para producción

Checklist operativo completo en `SECURITY_REVIEW.md` §8; puntos que esta fase confirma como
vigentes tras la validación final:

- `ENVIRONMENT=production` + `AUTH_SECRET_KEY`/`AUTH_PASSWORD` no-default + `CORS_ORIGINS` sin
  `localhost` — verificado que `main.py` aborta el arranque si alguno falla.
- `SYSTEM_VERSION` fijado en build time desde CI si el contenedor no incluye `.git` (de lo
  contrario `in_agent_executions.system_version` queda en `"unknown"`).
- HTTPS/TLS terminado en el reverse proxy — fuera del alcance de esta app.
- Definir política de retención de datos antes de manejar datos reales de clientes.
- Revisar logs de producción periódicamente en busca de datos sensibles filtrados en mensajes de
  excepción.
- Ejecutar `pytest` (backend), `npm test` (frontend), `ruff check --select E9,F,I` (backend) y
  `npm run lint` + `npm run build` (frontend) como parte de CI antes de cada despliegue — los
  cuatro corren limpios al cierre de esta fase y son baratos de mantener así.

---

**Fin de la Fase 10 — última fase del prompt maestro.** Ver el resumen final del estado de la
plataforma entregado en la conversación al cierre de esta fase.
