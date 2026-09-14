# SECURITY_REVIEW.md — Fase 9: Seguridad y preparación para producción

> Basado en todas las fases anteriores — en particular
> [QUALITY_OBSERVABILITY.md](QUALITY_OBSERVABILITY.md) (Fase 8), cuya recomendación de mayor
> prioridad ("inicializar git") se ejecuta en esta misma fase. A diferencia de las Fases 3-8, el
> prompt maestro pide aquí **revisar todo, pero implementar solo lo priorizado y seguro** — no
> todo lo encontrado se corrige en esta fase; lo que no se corrige queda documentado con severidad
> y plan de mitigación. 129/129 tests de backend (116 antes de esta fase + 13 nuevos).

## 0. El cambio de mayor impacto: el proyecto ahora tiene control de versiones

`git init` + primer commit (`0ea281d`), 133 archivos, sin secretos (`backend/.env` correctamente
excluido, verificado explícitamente antes de commitear). Esto no es solo higiene — **resuelve
directamente** la pregunta de auditoría que la Fase 8 dejó sin respuesta ("¿qué versión del sistema
generó este informe?"): `in_agent_executions.system_version` ahora captura el commit exacto (con
sufijo `-dirty` si había cambios sin commitear), verificado en vivo contra un informe real generado
en este mismo proceso.

Dos archivos `.docx` sueltos en la raíz (salidas generadas en fases exploratorias anteriores, no
código fuente) se excluyeron del repositorio vía `.gitignore` — siguen en disco, solo no están
versionados, misma categoría que `generated_reports/` ya excluido.

## 1. Autenticación

| Hallazgo | Severidad | Estado |
|---|---|---|
| Una sola credencial hardcodeada (`master`/`123456`) — aceptable para un operador único interno, inaceptable si se expone a clientes finales o crece a varios analistas | **Alto** (para multiusuario futuro) / Bajo (uso interno actual) | Documentado — rediseño real requiere Supabase Auth o similar, fuera de alcance de "cambios seguros" de esta fase |
| Sin límite de intentos de login — fuerza bruta trivial contra una contraseña de 6 dígitos | **Alto** | ✅ **Corregido esta fase**: límite de 10 intentos/5min por IP, en memoria (ver §7 sobre por qué no una solución distribuida) |
| `AUTH_SECRET_KEY`/`AUTH_PASSWORD` pueden quedar en sus valores por defecto sin que nadie lo note | **Alto** | ✅ **Corregido esta fase**: advertencia `CRITICAL` en el arranque si `ENVIRONMENT=production` y los valores siguen siendo los de desarrollo |
| Token JWT de 24h sin mecanismo de revocación — un token filtrado sigue siendo válido hasta expirar | Medio | No corregido — requeriría una lista de revocación o sesiones server-side, sobreingeniería para un solo usuario hoy |
| Sin MFA | Medio (Bajo mientras sea un solo operador interno) | No corregido — mismo razonamiento que roles/usuarios reales |

## 2. Autorización

| Hallazgo | Severidad | Estado |
|---|---|---|
| **Ninguna autorización por organización/cliente/informe** — cualquier sesión autenticada puede leer, renombrar o borrar cualquier conversación o informe, de cualquier empresa | **Alto** (para multiusuario/multiempresa real) / **Bajo hoy** (un solo usuario legítimo existe) | No corregido — es el hallazgo estructural más importante de toda la revisión, ya anticipado desde la Fase 0/1/2 como pregunta de negocio abierta ("¿cuántos analistas/organizaciones debe soportar la plataforma?"). Implementarlo bien requiere que exista la respuesta a esa pregunta primero |
| `in_users.role` existe en el esquema pero no se usa en ninguna decisión de acceso | Medio | No corregido — sin autorización real, un campo de rol sin aplicar sería falsa sensación de seguridad |
| `in_data_sources` no tiene control de acceso por usuario | Bajo hoy (una sola fuente, un solo usuario) | Documentado, no corregido |

## 3. Datos

| Hallazgo | Severidad | Estado |
|---|---|---|
| Sin política de retención — mensajes, informes y alarmas quedan indefinidamente | Medio | No corregido — requiere una decisión de negocio (¿cuánto tiempo debe conservarse un informe de un cliente?) antes de implementar borrado automático |
| Documentos generados (.docx/.pdf) viven en disco local sin cifrado propio más allá del sistema de archivos | Medio | Ya señalado desde la Fase 1 (migración a Supabase Storage, nunca implementada) — sigue pendiente |
| `raw_record` (fila cruda del Excel) circula hacia el LLM sin sanitizar — riesgo teórico de inyección de instrucciones si el dato de origen fuera menos confiable (ej. una API externa futura) | Medio | ✅ **Mitigado parcialmente esta fase**: los prompts de `narrative.py` y `answer_question.py` ahora indican explícitamente tratar los datos como datos, nunca como instrucciones — reduce pero no elimina el riesgo inherente a cualquier LLM |
| Logs no redactan datos sensibles de las excepciones (`exc_info=True` en varios `logger.warning`) | Bajo-Medio | Documentado, no corregido — bajo el volumen/exposición actual no es prioritario |
| Clasificación "CONFIDENCIAL" ya está en el documento mismo (branding del cliente), pero no hay control de acceso que la haga cumplir más allá de la autenticación básica | Medio | Depende directamente del hallazgo de Autorización (§2) |

## 4. Supabase

| Hallazgo | Severidad | Estado |
|---|---|---|
| RLS habilitado en las 12 tablas `in_*`, política acotada solo al rol `anon` | — (fortaleza, no hallazgo) | Confirmado correcto en esta revisión |
| Nunca se usa la `service_role key` en el backend — evita saltarse RLS por completo | — (fortaleza) | Confirmado correcto |
| La clave `anon` es, en la práctica, un secreto compartido: si se filtra, da acceso completo de lectura/escritura a las 12 tablas `in_*` (aunque no a las tablas de otras apps en el mismo proyecto Supabase, gracias al aislamiento por prefijo + políticas propias) | **Alto** si se filtra | Mitigación existente: la clave vive solo en `backend/.env`, nunca se envía al frontend (verificado en cada fase). No hay rotación automática — recomendado para el checklist de producción |
| Sin buckets de Supabase Storage en uso — los documentos siguen en disco local (Fase 7) | Medio | Ya documentado como brecha desde la Fase 1, sigue pendiente |
| `in_data_sources.config` no contiene secretos hoy (única fuente activa es el Excel, sin credenciales) | — | Regla ya establecida (Fase 2) para cuando exista una fuente que sí los necesite |

## 5. Agente

| Hallazgo | Severidad | Estado |
|---|---|---|
| `answer_question` acota `company_id`/`start_date`/`end_date` en el cierre de la función (variables de Python capturadas del estado del servidor) — **el modelo no puede pedir datos de otra empresa** vía argumentos de herramienta, aunque lo intente | — (fortaleza) | Confirmado correcto en esta revisión — verificado leyendo el código, no asumido |
| Prompt injection vía campos de texto libre (descripción de alarma) que llegan al LLM | Medio | ✅ **Mitigado esta fase** (ver §3) — riesgo inherente a cualquier sistema con datos de origen menos que 100% confiables, no eliminable con prompting únicamente |
| Sin límite de costo/frecuencia por usuario para disparar generación de informes (cara: LLM + LibreOffice) | Medio | No corregido — con un solo usuario hoy no es explotable por terceros, pero es un vector real de costo descontrolado si se abre a más usuarios sin límite |
| El conjunto de herramientas de `answer_question` es fijo y de solo lectura — sin superficie de ejecución de código arbitrario | — (fortaleza) | Confirmado |

## 6. APIs

| Hallazgo | Severidad | Estado |
|---|---|---|
| `/api/auth/login` sin límite de intentos | Alto | ✅ **Corregido esta fase** (§1) |
| Ningún otro endpoint tiene rate limiting — `/api/reports/generate` en particular es costoso (LLM + PDF) y no tiene límite | Medio | No corregido esta fase — mismo razonamiento que el punto de Agente arriba; recomendado como el siguiente rate-limit a agregar si el uso crece |
| `CORS_ORIGINS` apunta a `localhost` por defecto | Medio si se despliega sin cambiarlo | ✅ **Mitigado esta fase**: advertencia de arranque si `ENVIRONMENT=production` y sigue apuntando a localhost |
| Sin límites explícitos de tamaño de request (se usan los valores por defecto de Starlette) | Bajo | Documentado, aceptable para el volumen actual |
| Timeouts: LibreOffice tiene 60s explícito (Fase 7); las llamadas al LLM usan los valores por defecto del SDK, sin timeout propio de la app | Bajo-Medio | Documentado, no corregido |
| Sin reintentos automáticos ante fallos transitorios de Anthropic/Supabase (una falla se propaga tal cual al usuario) | Bajo | Ya documentado como decisión consciente desde fases anteriores (simplicidad sobre resiliencia automática al volumen actual) |

## 7. Por qué el rate limiter es en memoria y no distribuido

Se decidió explícitamente **no** agregar Redis/una cola compartida para esto: el proyecto es de una
sola instancia (`ARCHITECTURE_TARGET.md`, notas de escalabilidad), así que un contador en memoria
del propio proceso ya cumple el objetivo (frenar fuerza bruta contra un login público) sin
infraestructura nueva. Se documenta explícitamente como **no correcto si el backend llega a correr
en más de una réplica** (cada una tendría su propio contador) — ítem del checklist de producción.

## 8. Checklist de producción

- [ ] `ENVIRONMENT=production` en el `.env` real (activa las advertencias de arranque de esta fase)
- [ ] `AUTH_SECRET_KEY` generado aleatoriamente (no el valor de desarrollo)
- [ ] `AUTH_USERNAME`/`AUTH_PASSWORD` cambiados del valor por defecto
- [ ] `CORS_ORIGINS` apuntando al dominio real del frontend, sin `localhost`
- [ ] `SYSTEM_VERSION` fijado en build time desde CI (`git rev-parse --short HEAD`) si el
      contenedor no incluye `.git`
- [ ] HTTPS/TLS terminado en el reverse proxy (fuera del alcance de esta app — FastAPI no lo hace)
- [ ] Rotación de la clave `anon` de Supabase si alguna vez hay sospecha de filtración
- [ ] Decidir y documentar una política de retención de datos antes de tener clientes reales con
      datos sensibles de producción (no sintéticos)
- [ ] Si se abre el acceso a más de un analista: implementar autorización real por
      organización/cliente **antes**, no después (§2 — es el hallazgo de mayor impacto pendiente)
- [ ] Si se despliega en más de una réplica: mover el rate limiter de `/login` a un almacén
      compartido (§7)
- [ ] Revisar logs de producción periódicamente en busca de datos sensibles filtrados en mensajes
      de excepción

## 9. Plan de mitigación (orden sugerido, más allá de esta fase)

1. **Autorización real por organización/cliente** (§2) — el ítem de mayor impacto, bloqueado
   detrás de una decisión de negocio ya señalada en fases anteriores, no una tarea puramente
   técnica.
2. **Migrar documentos a Supabase Storage** (§3/§4) — ya diseñado desde la Fase 1/2, nunca
   implementado.
3. **Rate limiting en `/api/reports/generate`** (§6) — extensión directa del mecanismo ya
   construido esta fase para `/login`.
4. **Política de retención de datos** (§3) — requiere definición de negocio antes de código.
5. **MFA / gestión de usuarios real** (§1) — junto con el punto 1, cuando exista más de un usuario
   legítimo.

---

**Fin de la Fase 9.** Backend: 129/129 tests. Cambios implementados: control de versiones (git),
límite de intentos de login, advertencias de arranque contra configuración insegura en producción,
trazabilidad de versión del sistema por ejecución, y endurecimiento de prompts contra inyección de
instrucciones vía datos. Todo lo demás queda documentado con severidad y plan de mitigación, no
implementado, siguiendo la instrucción explícita de esta fase de corregir solo lo priorizado y
seguro. Quedo a la espera de tu aprobación para iniciar la Fase 10 (integración final y
documentación).
