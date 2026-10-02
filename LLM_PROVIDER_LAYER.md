# LLM Provider Layer — Multi-LLM (Cloud / Local / vLLM / Auto)

## Arquitectura

```
Data Sources → Normalization → LangGraph → LLM Provider Layer → Proveedor elegido → LLM → Validation → DOCX
                                               │
                                               ├── Cloud  (Anthropic · OpenAI · Gemini)
                                               ├── vLLM   (servidor propio, API compatible con OpenAI)
                                               ├── Local  (Ollama u otro servidor compatible)
                                               └── Auto   (orden configurable + fallback)
```

- **`app/llm/`** — la capa, sin dependencias de Supabase ni de la app:
  - `types.py` (proveedores, estados de salud, parámetros normalizados),
  - `adapters/` (un adaptador por proveedor),
  - `registry.py` (qué proveedor puede ocupar cada ranura),
  - `layer.py` (`resolve` → `chat_model`),
  - `fallback.py` (modelo con *failover* entregado a LangGraph),
  - `errors.py` (clasificación de fallos).
- **`app/services/llm_runtime.py`** — la ejecución de cada solicitud. La selección vive en un *contextvar*, así llega al nodo que hace la inferencia sin tocar el grafo. Además emite los eventos SSE `llm` y las métricas de observabilidad y auditoría.
- **`app/services/llm_settings_service.py`** — persistencia en Supabase (`in_llm_providers`, `in_llm_routing`) con las API keys cifradas.
- **`app/agents/llm.py`** — `get_chat_model()`, la única puerta de los nodos. LangGraph sigue usando `with_structured_output`, `bind_tools` y `ainvoke`, y no conoce proveedores.

```python
resolution = await layer.resolve(LLMSelection("auto"))   # resolveProvider + resolveModel
llm = layer.chat_model(resolution, observer)              # createLLM (con failover en Auto)
```

## Selección por solicitud

`POST /api/reports/generate` y `POST /api/conversations/{id}/messages` aceptan `llm: {provider, model}`. Si se omite, se usa la preferencia del usuario (Configuración) y, si no hay, el proveedor predeterminado de la app.

- **Proveedor explícito:** se respeta. Antes de empezar se hace un health check; si falla, se informa el motivo y no se cambia a otro proveedor.
- **Auto:**
  1. recorre el orden configurado (p. ej. vLLM → Cloud) y usa el primer proveedor disponible;
  2. si una llamada falla por timeout, conexión, error 5xx, autenticación, modelo inexistente o límite de uso, continúa con el siguiente;
  3. cada cambio se informa en la UI (evento `llm` con fase `fallback`), en Observabilidad (WARNING `llm.provider_fallback`) y en Auditoría (`llm.provider_fallback`, con origen, destino, motivo y etapa).
- **Errores de salida del modelo** (por ejemplo, un JSON inválido) no provocan cambio de proveedor: son problemas de calidad, no de disponibilidad.

## Health check

Cada adaptador implementa `health()` y devuelve uno de estos estados:
- disponible;
- no disponible;
- error de autenticación;
- timeout;
- modelo no disponible;
- error de conexión;
- error del servidor;
- límite de uso;
- sin configurar;
- deshabilitado.

Junto con el estado devuelve la latencia aproximada. Los resultados se guardan en caché con un TTL configurable.

## Agregar un proveedor

1. Implementar `ProviderAdapter`, con tres métodos: `list_models`, `create_chat_model` y, opcionalmente, `health`.
2. Registrarlo en `ADAPTER_CLASSES` y en la ranura que corresponda de `VENDORS_BY_PROVIDER`.
3. Agregar el valor en la restricción `vendor` de `in_llm_providers`.

LangGraph, el pipeline y la UI no cambian.

## Parámetros

Los parámetros admitidos son:
- temperatura;
- max tokens;
- top P;
- timeout;
- ventana de contexto;
- método de salida estructurada.

Cada adaptador descarta los parámetros que su proveedor no admite. Por ejemplo, Claude no acepta temperatura y top P juntos, así que se envía solo la temperatura.

## Seguridad

- Las API keys se cifran con `SOURCE_SECRET_KEY` (Fernet) y solo se guardan en claro sus últimos 4 caracteres, como pista para la UI. Nunca se devuelven al frontend ni se registran.
- Toda llamada que necesita un secreto se ejecuta en el backend.
- La redacción de logs oculta claves con formato de proveedor (`sk-…`, `AIza…`) y JWT.
- Solo los administradores configuran proveedores, enrutamiento y evaluaciones; los miembros solo eligen entre proveedores habilitados.
- RLS: los miembros leen la configuración que necesitan para trabajar; las evaluaciones son solo para administradores.
- Observabilidad: por cada llamada se registran proveedor, modelo, request id, latencia, estado, tokens y si hubo fallback. Nunca se guardan prompts ni respuestas.
- Con Cloud, los datos del informe salen hacia el proveedor elegido; con vLLM o Local se quedan en la infraestructura propia.
- Las URL de los proveedores las define un administrador, y el backend las consulta para health checks y descubrimiento de modelos. Es un riesgo aceptado: solo los administradores pueden cambiarlas.

## Evaluación de calidad

`Configuración > Evaluación de IA` (o `POST /api/llm/evaluations`) ejecuta los mismos casos (`data/llm_eval_cases.json`, datos sintéticos) con cada candidato, usando los prompts reales de la app.

Mide:
- exactitud de extracción;
- clasificación de severidad;
- identificación de riesgos;
- calidad de las recomendaciones (sustento en alarmas reales);
- calidad del informe (validación y completitud);
- consistencia entre repeticiones;
- latencia, errores y tokens.

El resultado marca como **degradación** cualquier caída de más de 5 puntos frente a la línea base (el primer candidato).

## Migración

Ejecutar `supabase/migrations/20261003000000_in_llm_providers.sql`. Crea `in_llm_providers`, `in_llm_routing` e `in_llm_evaluations`, agrega a `in_agent_executions` las columnas de proveedor y fallback, y suma la categoría `llm` a la observabilidad.
