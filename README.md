# AI Security Report Generator

AI-assisted platform that turns a CSOC operator's request — typed in chat or filled into a
form — into a client-branded security management report (Word or PDF), backed by real alarm
data and grounded, evidence-cited narrative. Reports can be regenerated conversationally
("hazlo más ejecutivo", "enfócalo solo en Agente desconectado") without re-fetching data unless
the underlying parameters actually change.

All data is **synthetic** — including `data/thomas_tgs_tps_alarmas_julio.xlsx`, a client-shaped
alarm export the project owner provided for realism, which does not represent any real company,
incident, or security posture.

## Qué hace la app

- **Genera informes de gestión CSOC** para una empresa y período dados, a partir de datos reales
  de alarmas entregados por la fuente de datos del cliente (o un dataset mock para demos), en formato
  **Word (.docx) o PDF**.
- **Dos modalidades de uso**, ambas ejecutando exactamente la misma lógica interna
  (`app/services/report/*`) — ver "Flujo determinístico" y "Flujo conversacional" abajo.
- **Responde preguntas puntuales sobre los datos** ("¿cuáles son las alarmas críticas?", "¿cómo
  evolucionaron las alarmas de julio a agosto?") citando únicamente alarmas verificadas por
  herramienta — nunca un `alarm_number` inventado (ver `AGENT_ARCHITECTURE.md`).
- **Versiona cada regeneración** de un informe (`report_versions`) y conserva el historial
  completo de la conversación, recuperable tras recargar la página.
- **Registra cada ejecución** (modo, modelo, tokens, costo estimado, duración, versión del
  sistema, errores) en `in_agent_executions` para observabilidad (ver `QUALITY_OBSERVABILITY.md`).

## Arquitectura

Monolito modular: un backend FastAPI ejecuta un agente LangGraph (un único `StateGraph`, sin
supervisor/subagentes) detrás de una abstracción `DataProvider` (`HttpSourceDataProvider` por
defecto, `MockDataProvider` como alternativa sintética — ninguno de los dos toca el agente ni
las tools), y un frontend React lo consume vía REST + SSE. Entre la fuente remota y el
`DataProvider` hay una capa de adquisición aislada del agente (`backend/app/ingestion/`).

```
frontend/   React + TypeScript + Vite + Tailwind + Zustand -- chat UI y formulario
backend/    FastAPI + LangGraph agent + tools + providers (http/mock) + ingestion (fuente remota)
            + python-docx builder
data/       companies.json (lista oficial de empresas del cliente), mitre_tactics.json (catálogo
            estático MITRE ATT&CK), mock_security_data.json (+ scripts/generate_mock_data.py)
```

El esqueleto de secciones del informe (`templates.py`, hoy un único template
`csoc_mensual`) es fijo en código, no algo que el LLM decide turno a turno — el LLM solo redacta
prosa breve y evidenciada (`ReportNarrative`) para un puñado de campos, más recomendaciones
respaldadas por evidencia. `python-docx` construye el `.docx` final a partir de la
`ReportSpecification` validada — nunca texto libre del LLM, y nunca una cita de alarma
fabricada (`ReportSpecification.validate_evidence` verifica cada `alarm_number` citado contra lo
realmente recolectado). Para PDF, el `.docx` se convierte con LibreOffice en modo headless
(`soffice_binary`, ver `app/services/report/document.py`).

Ambas modalidades (formulario y chat) comparten la misma capa de servicios
(`app/services/report/`: `collection.py`, `analysis.py`, `specification.py`, `validation.py`,
`document.py`, `execution_tracking.py`, `cost_estimation.py`) — el flujo determinístico
(`pipeline.run_deterministic`) la invoca directamente en un orden fijo; el flujo conversacional
la invoca desde los nodos del grafo LangGraph. Ver `DETERMINISTIC_FLOW.md`,
`AGENT_ARCHITECTURE.md` y `REPORT_GENERATION_ARCHITECTURE.md` para el detalle de cada uno.

### Fuente de datos (`DATA_PROVIDER=http`) y capa de adquisición

Las alarmas se piden directamente a la fuente del cliente (Albatrus SOC): el export CSV
`detallado_alarmas.php` (una fila por alarma) y el panel `indicadores.php` (totales y tops, usado
para conciliar). La fuente pide un **login por formulario**; el cliente lo completa solo con las
credenciales del entorno. Todo lo que cambia entre ambientes vive en `backend/.env` (nunca en el
código ni en la base de datos):

```
SOURCE_BASE_URL=http://10.2.85.8/ProyectoSOC/views   # cambiar la IP = editar esta línea y reiniciar
SOURCE_USERNAME=...  SOURCE_PASSWORD=...             # solo variables de entorno
SOURCE_VERIFY_TLS=true                               # si es https; o SOURCE_CA_BUNDLE=/ruta/ca.pem
```

> La fuente se sirve hoy por **http**: credenciales y datos viajan sin cifrar. Usarla solo por la
> VPN/LAN y pedir https al proveedor (el backend lo advierte al arrancar).

**Cambiar la IP, el usuario o la contraseña desde la app:** barra lateral → **Fuente de datos**.
Se prueba la conexión antes de guardar y el cambio aplica de inmediato, sin reiniciar. Los valores
guardados ahí tienen prioridad sobre `backend/.env` y quedan en `backend/source_settings.json`
(permisos 0600, fuera de git); la contraseña nunca se vuelve a mostrar.

`backend/app/ingestion/` es una capa **separada del agente** (nada en `app/agents` ni
`app/services/report` la importa): `config.py` (SOURCE_* → `SourceConfig`), `requests.py`
(construye las URLs de alarmas/indicadores y corrige los bordes de fechas de cada endpoint),
`client.py` (Basic Auth + login por formulario restringido al mismo host, sesión reutilizable y
renovación si expira, errores accionables), `csv_decoder.py` (bytes → tabla; detecta HTML con
HTTP 200), `normalizer.py` (filas → `NormalizedSecurityAlert`), `indicators_parser.py` (HTML del
panel → `SourceIndicators`) y `service.py` (pide, valida que las filas sean de la empresa pedida,
concilia el total con el panel y cachea por empresa/período). `HttpSourceDataProvider` solo adapta
eso al contrato `DataProvider`. Ver `INGESTION_ARCHITECTURE.md` (§8) para el detalle.

- **`mock`** — `MockDataProvider`, completamente sintético, sin servidor ni credenciales. Útil
  para demos/tests (`DATA_PROVIDER=mock`).
- El proveedor Excel y el placeholder `api` fueron **eliminados**; seleccionarlos da un error
  explícito que pide usar `DATA_PROVIDER=http`.
- **Verificar la conexión** (desde una máquina con acceso a la fuente/VPN):
  `cd backend && python scripts/probe_sources.py --company "THOMAS TGS TPS" --indicators` — prueba
  las variantes de `cliente=`, muestra columnas/estadísticas y nunca imprime credenciales.

### Empresas (registro central)

La lista oficial del cliente (18 empresas: *Nombre empresa informe*, *Logo*, *Consecutivo
Albatroz*) vive en `data/companies.json` y se carga a la tabla `in_companies` de Supabase con
`cd backend && python scripts/seed_companies.py` (idempotente). En runtime la fuente de verdad es la
tabla (`app/services/company_registry.py`): de ahí salen el selector del formulario, los nombres
en la app y en el informe, el valor de `cliente=` de cada request (`source_client`, o el nombre si
está vacío) y el logo (`logo_key` → `backend/app/document/assets/logos/`, ver su README). Un texto
que coincide con varias empresas (p. ej. "peru") **no se adivina**: se pide elegir entre las opciones.

### Autenticación y almacenamiento de conversaciones

La app está detrás de un único login de operador hardcodeado (`AUTH_USERNAME`/`AUTH_PASSWORD` en
`backend/.env`, default `master`/`123456`) en lugar de cuentas por usuario — solo existe un par
de credenciales, así que Supabase Auth completo sería más maquinaria de la que el requerimiento
pide. `POST /api/auth/login` emite un JWT firmado (`backend/app/auth.py`, con un rate limiter de
10 intentos/5 min por IP); cada ruta `/api/conversations*` y `/api/reports*` lo exige como Bearer
token.

Conversaciones, mensajes, informes y versiones de informe viven en Supabase Postgres, en tablas
con prefijo `in_` (`in_conversations`, `in_messages`, `in_reports`, `in_report_versions`,
`in_agent_executions` — ver `backend/app/services/repositories.py` y
`backend/app/services/supabase_rest.py`) para no colisionar con nada más en un proyecto Supabase
compartido. El backend habla con ellas por PostgREST usando la anon key del proyecto, que se
mantiene solo del lado del servidor (`backend/.env`, nunca se envía al frontend); las políticas
RLS en esas tablas le otorgan acceso completo solo a ellas. Las conversaciones pueden
renombrarse, anclarse y eliminarse desde la barra lateral.

El checkpointer de LangGraph (estado del agente por conversación) es independiente y sigue
usando su propio archivo SQLite local (`agent_checkpoints.sqlite3`).

### Seguridad

Ver `SECURITY_REVIEW.md` para el detalle. En resumen: al arrancar en `ENVIRONMENT=production`,
`main.py` verifica que `AUTH_SECRET_KEY`/`AUTH_PASSWORD` ya no tengan sus valores de desarrollo y
que `CORS_ORIGINS` no siga apuntando a `localhost`, abortando el arranque si algo de eso falla.
El login tiene rate limiting; los tools del agente son explícitos y tipados (Pydantic), nunca
ejecutan SQL/código arbitrario provisto por el LLM.

## Instalación

### Prerrequisitos

- Una API key de Anthropic (el agente usa Claude vía `langchain-anthropic`)
- Un proyecto Supabase (para almacenamiento de conversaciones/informes)
- LibreOffice instalado y accesible como `soffice` en el PATH (necesario solo para exportar a
  PDF — la generación en `.docx` no lo requiere)
- Docker + Docker Compose, **o** Python 3.12+ y Node 20+ para correr las dos apps directamente

### Variables de entorno (`backend/.env`)

Copiar `backend/.env.example` a `backend/.env` y completar:

| Variable | Descripción |
|---|---|
| `ANTHROPIC_API_KEY` | API key de Anthropic (requerida) |
| `LLM_MODEL` | Modelo Claude a usar (default `claude-sonnet-5`) |
| `DATA_PROVIDER` | `http` (default, fuente remota) o `mock` |
| `SOURCE_BASE_URL` | Dirección de la fuente, p. ej. `http://10.2.85.8/ProyectoSOC/views` — **único lugar** donde cambia la IP |
| `SOURCE_USERNAME` / `SOURCE_PASSWORD` | Credenciales de la fuente, usadas en el login por formulario y como Basic Auth (solo entorno; nunca versionar `.env`) |
| `SOURCE_VERIFY_TLS` / `SOURCE_CA_BUNDLE` | Verificación TLS (default `true`); CA propia vía `SOURCE_CA_BUNDLE` |
| `SOURCE_ALARMS_PATH` / `SOURCE_INDICATORS_PATH` | Rutas de los endpoints (defaults `/detallado_alarmas.php`, `/indicadores.php`); también aceptan una URL completa si un endpoint vive en otro host |
| `SOURCE_RECONCILE_INDICATORS` | Conciliar cada descarga con el total del panel de indicadores (default `true`) |
| `SOURCE_SETTINGS_PATH` | Archivo donde la app guarda dirección/usuario/contraseña editados desde **Fuente de datos** (default `backend/source_settings.json`; en Docker, `/app/storage/source_settings.json`) |
| `SOURCE_TIMEOUT_SECONDS` / `SOURCE_ALARMS_LIMIT` / `SOURCE_CACHE_TTL_SECONDS` | Timeout (30), `limite=` por request (1000) y vigencia del caché (300 s) |
| `MOCK_DATA_PATH` / `MITRE_TACTICS_PATH` | Overrides de ruta; por defecto apuntan a `data/` en la raíz del proyecto |
| `CORS_ORIGINS` | Lista JSON de orígenes permitidos (default `["http://localhost:5173"]`) |
| `SUPABASE_URL` / `SUPABASE_ANON_KEY` | Proyecto Supabase para conversaciones/informes |
| `AUTH_USERNAME` / `AUTH_PASSWORD` | Credencial única de operador |
| `AUTH_SECRET_KEY` | Secreto de firma del JWT — cambiar en cualquier despliegue real |
| `ENVIRONMENT` | `development` (default) o `production` — activa las validaciones de `SECURITY_REVIEW.md` |
| `SYSTEM_VERSION` | Opcional; fija `in_agent_executions.system_version` en vez de leer `git rev-parse HEAD` en runtime (útil en imágenes Docker sin `.git`) |

## Ejecución local

### Con Docker Compose

```bash
cp backend/.env.example backend/.env   # completar ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY
ANTHROPIC_API_KEY=sk-ant-... docker compose up --build
```

- Frontend: http://localhost:5173
- Backend: http://localhost:8000 (docs interactivas en `/docs`)

### Sin Docker

Backend:

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completar ANTHROPIC_API_KEY, SUPABASE_URL, SUPABASE_ANON_KEY
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Configuración de Supabase

1. Crear un proyecto en [supabase.com](https://supabase.com).
2. Crear las tablas `in_conversations`, `in_messages`, `in_reports`, `in_report_versions`,
   `in_agent_executions` (ver `DATA_MODEL.md` para el esquema completo de cada una).
3. Habilitar RLS en esas tablas y crear una política que otorgue acceso completo a la anon key
   del proyecto — ver `SECURITY_REVIEW.md` para el razonamiento (la anon key vive solo en el
   backend, nunca se expone al cliente, y queda deliberadamente acotada a las tablas `in_*`).
4. Copiar la URL del proyecto y la anon key a `SUPABASE_URL` / `SUPABASE_ANON_KEY` en
   `backend/.env`.
5. Cargar la lista de empresas del cliente: `cd backend && python scripts/seed_companies.py`
   (requiere las columnas `logo_key`, `consecutivo`, `source_client`, `is_active`, `updated_at` de
   `in_companies`, ya incluidas en `supabase_schema.sql`).

El checkpointer de LangGraph (estado conversacional del agente) **no** vive en Supabase — usa su
propio SQLite local y no requiere configuración adicional.

## Uso del flujo determinístico (Formulario)

Pestaña "Formulario" del frontend, o `POST /api/reports/generate` directamente. El operador
selecciona empresa, tipo de informe, rango de fechas, nivel de detalle (general/ejecutivo/
técnico), formato de salida (docx/pdf), categorías de alerta y niveles de severidad a incluir, y
ejecuta la generación. El sistema:

1. valida los parámetros (empresa/fechas/formato),
2. consulta los datos del período (`collect`),
3. analiza los datos recolectados (`analyze`),
4. genera la especificación del informe (`build_specification`),
5. valida la especificación (citas de alarma, secciones requeridas),
6. genera el documento (`.docx` o `.pdf`),
7. guarda el informe y su versión, registra la ejecución en `in_agent_executions`,
8. el operador descarga el documento.

Es el mismo pipeline en el mismo orden en cada ejecución — sin decisiones del LLM sobre qué paso
correr, lo que lo hace reproducible dado el mismo input. Ver `DETERMINISTIC_FLOW.md`.

## Uso del chatbot (flujo conversacional)

Pestaña "Chat". El operador escribe en lenguaje natural, p. ej.:

```
Usuario: Genera un informe de seguridad de THOMAS TGS-TPS para julio de 2026.
IA:      [identifica empresa/período, consulta los datos, analiza, genera el informe]
         Tu informe de gestión está listo — 8 secciones. [Descargar Informe (.docx)]

Usuario: Hazlo más ejecutivo.
IA:      [reutiliza los datos ya recolectados, solo regenera la narrativa] v2 lista.

Usuario: Genera el documento en PDF.
IA:      [regenera el documento en el formato solicitado] v3 lista — Descargar Informe (.pdf)

Usuario: ¿Cuáles son las técnicas MITRE ATT&CK más frecuentes este período?
IA:      [consulta las alarmas del período vía tool, responde solo con lo verificado]
```

Cada regeneración queda como una nueva fila en `report_versions`, recuperable vía
`GET /api/reports/{report_id}`; el historial completo de la conversación persiste y se
reconstruye al recargar la página. Preguntas sobre los datos (sin pedir generar/modificar el
informe) se resuelven con `answer_question`, el único nodo con tool-calling real del agente —
cada alarma citada en la respuesta se verifica contra lo que las tools efectivamente devolvieron
ese turno; si el modelo cita algo no verificado, la cita se descarta antes de mostrarse. Ver
`AGENT_ARCHITECTURE.md` y `CONVERSATIONAL_EXPERIENCE.md`.

## Incorporación de nuevas fuentes de datos

Toda fuente de datos implementa el contrato `DataProvider` (`backend/app/providers/base.py`) —
ni el agente ni las tools conocen el origen concreto de los datos. Para agregar una fuente
nueva (p. ej. otra API del cliente):

1. Implementar cada método de `DataProvider` mapeando la fuente a los modelos de dominio
   (`app/models/domain.py`: `NormalizedSecurityAlert`, `Company`, etc.), aplicando el mismo rigor
   de validación que `app/ingestion/normalizer.py` (campos requeridos, fechas, duplicados). Si la
   nueva fuente entrega las mismas columnas, basta un nuevo decodificador (bytes → tabla) y
   reutilizar `normalize_alarm_rows`; las empresas siempre salen del registro.
2. Reusar `ingestion_service.record_import` (listener `on_fetch` del servicio de adquisición) para
   registrar metadata de importación (`data_source_id`, hash del payload, warnings).
3. Registrar el nuevo proveedor detrás de `DATA_PROVIDER` en `settings.py` y
   `app/providers/factory.py` (o el punto de selección equivalente).

Nada en el pipeline de generación de informes (`specification.py`, el agente, el endpoint
determinístico) cambia — todos consumen `DataProvider`, no un proveedor concreto.

## Generación de informes

Ver "Uso del flujo determinístico" y "Uso del chatbot" arriba — ambos caminos terminan en el
mismo `build_specification` + `render`. Para agregar un nuevo template de informe (hoy solo
existe `csoc_mensual`), escribir una función con la firma `TemplateBuilder` en
`app/services/report/templates.py` y registrarla con `register_template()` — ver
`REPORT_GENERATION_ARCHITECTURE.md`.

## Regenerar el dataset mock

```bash
python3 scripts/generate_mock_data.py
```

## Tests, lint y build

```bash
# backend -- tests
cd backend && source .venv/bin/activate && pytest

# backend -- lint (ruff; solo errores de sintaxis, pyflakes e imports desordenados)
cd backend && source .venv/bin/activate && ruff check app tests evals --select E9,F,I

# frontend -- tests
cd frontend && npm test

# frontend -- lint
cd frontend && npm run lint

# frontend -- build de producción
cd frontend && npm run build
```

El agente LangGraph testea con LLM calls stubbeadas (`backend/tests/test_agent_graph.py`), así
que el flujo completo — informe nuevo, pausa por aclaración, y modificación en contexto sin
re-consultar datos — se verifica sin necesitar una API key real.

### LLM quality eval (TruLens)

Pytest verifica corrección de código; no verifica si la narrativa del LLM está realmente
fundamentada en los datos que recibió. `backend/evals/` tiene un eval de groundedness basado en
TruLens que corre la llamada real de generación de narrativa contra datos reales del cliente y
la puntúa con Claude como juez — ver `backend/evals/README.md`. Requiere una API key real y un
venv separado (Streamlit/TruLens no son dependencias de la app).

## Notas sobre desviaciones del stack tecnológico original

- **python-docx en vez de PptxGenJS/python-pptx** — el informe recurrente real del cliente
  resultó ser un documento Word (`.docx`), no una presentación. Se cambió de PowerPoint a Word
  para coincidir, manteniendo el generador en el mismo lenguaje que el backend/agente.
- La persistencia del estado de conversación usa el propio checkpointer `AsyncSqliteSaver` de
  LangGraph (indexado por `conversation_id`) en vez de almacenamiento de estado hecho a mano.
- Los nombres/descripciones de tácticas MITRE ATT&CK se resuelven contra un catálogo estático
  (`data/mitre_tactics.json`, tomado de la propia hoja de referencia "ID Mitre" del cliente) en
  vez de confiar en la etiqueta de texto libre de cada fila.
- La sección 6.1 (top de destinatarios de rareza de correo) lee el pivot ya calculado por el
  cliente (`ingest_email_rarity_ranking`) en vez de recalcularlo desde el log crudo de ~34k
  filas — sus números son la fuente de verdad ya publicada en su informe.

## Documentación adicional

Ver `FINAL_ARCHITECTURE.md` para la arquitectura final consolidada, decisiones técnicas,
limitaciones conocidas y roadmap. Los documentos de arquitectura por fase
(`ARCHITECTURE_ASSESSMENT.md`, `ARCHITECTURE_TARGET.md`, `DATA_MODEL.md`,
`INGESTION_ARCHITECTURE.md`, `AGENT_ARCHITECTURE.md`, `DETERMINISTIC_FLOW.md`,
`CONVERSATIONAL_EXPERIENCE.md`, `REPORT_GENERATION_ARCHITECTURE.md`,
`QUALITY_OBSERVABILITY.md`, `SECURITY_REVIEW.md`) documentan cada decisión con su contexto
original y siguen siendo la referencia de detalle para cada subsistema.
