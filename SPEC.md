# Especificación Técnica — MCP de Consulta REPSE

**Proyecto:** `repse-mcp`
**Cliente/Producto:** WATR Inc. (We Are The Robots)
**Autor:** Eduardo Ortiz Ramírez (CEO)
**Versión:** 2.0
**Fecha:** 2 de agosto de 2026
**Estado:** Implementada (reemplaza al draft v1.0 del 15-jul-2026)

---

## 1. Resumen ejecutivo

Servidor **MCP** que expone el **Padrón Público de Contratistas de Servicios Especializados u Obras Especializadas (REPSE)** de la STPS como herramientas consumibles por agentes LLM y flujos de cumplimiento: consulta puntual, verificación de cartera, búsqueda masiva y ventanas de vencimiento.

### Qué cambió respecto a la v1.0

La v1.0 partía de la premisa *"REPSE no ofrece API oficial → descarga del padrón + scraping del portal `repse.stps.gob.mx/Publico`"* y derivaba de ahí un índice con frescura ≤24 h, scraping headless con p95 de 8 s, y toda la infraestructura correspondiente. **Verificado contra el portal el 2026-08-01, la premisa era falsa:**

| v1.0 asumía | Realidad verificada |
|---|---|
| `/Publico` como portal de consulta | Da **404**; el portal vive en la raíz |
| Sin acceso programático | **Dos endpoints JSON públicos sin auth**: `GET /busca_razon_social?term=…` y `POST /buscar-padron` |
| Scraping headless, <8 s p95 | HTTP simple (cookie + CSRF de Laravel), **~800 ms** extremo a extremo |
| Sin descarga estructurada | **`GET /padron-public-excel`**: xlsx de ~26 MB con el padrón completo (~155k filas) |
| Índice con Turso + pipeline + frescura ≤24 h | Consulta puntual **en vivo** (frescura total); índice local **rebuild-on-boot** sin Turso |

## 2. Arquitectura

Dos rutas de datos, cada una para lo que es mejor:

1. **En vivo** (`client.py` → `consulta.py` → `risk.py`): verificación puntual y por lote. El typeahead acepta RFC/folio/razón social; el detalle regresa RFC, vigencia y actividades. El veredicto es **determinista** (aritmética de fechas, sin IA).
2. **Índice local** (`padron.py`): SQLite+FTS5 construido desde el xlsx público. Da lo que el typeahead no puede: **búsqueda masiva con paginación** (el vivo tapa en 30 resultados sin paginar) y **ventanas de vencimiento**. Se reconstruye al boot si está vacío/viejo y a diario vía cron de GitHub Actions → `POST /refresh`.

### Hechos no obvios de la fuente (los que muerden)

- **`registro: 1` NO significa vigente.** El detalle regresa `registro: 1` para registros ya vencidos (caso real: `ASE100712TT2`, vencido 2024-09-10). Significa "lo encontré", no "está vigente". La vigencia se calcula contra `fecha_vencimiento_registro`. Cubierto por test.
- **El xlsx no trae RFC** (columnas: Folio, Razón Social, Estado, Municipio, Vigencia, Actividades). Por eso la verificación por RFC es siempre en vivo.
- **El typeahead hace match parcial** y puede regresar homónimos: con RFC se abre el detalle y se exige coincidencia exacta antes de aprobar (`consulta.py`).
- El xlsx usa **strings inline** (no sharedStrings) → parser stdlib propio (zipfile + iterparse), sin pandas/openpyxl.
- `/padron-public-excel` **no está enlazado** en el home (se descubrió vía índice de buscadores). Toda ruta de fuente es overrideable por env (`REPSE_BASE_URL`, `REPSE_PATH_*`): la STPS ya movió rutas antes.
- **Guards de frescura** en el import: <100k filas o `max(vigencia)` que retrocede ⇒ aborta conservando el índice anterior. Un HTTP 200 no es evidencia de datos frescos (lección sat69/69-B).

### Por qué sin Turso

La fuente es un solo archivo público que descarga y parsea en ~10 s total: reconstruir es más barato que persistir. Disparador de reversa documentado: si la STPS bloquea/limita descargas desde datacenter, se siembra Turso desde GitHub Actions (patrón `sat69-mcp`).

## 3. Tools (5)

| Tool | Ruta de datos | Qué regresa |
|---|---|---|
| `verificar_repse(termino)` | vivo | veredicto {estado, vigente, fecha_vencimiento, RFC, actividades} |
| `verificar_lote(rfcs)` | vivo (4 hilos) | conteos por estado + **sólo** los no-vigentes |
| `buscar_padron(texto, entidad, limite, offset)` | índice (fallback vivo) | búsqueda FTS paginada por razón social/actividad |
| `por_vencer(dias, entidad, limite)` | índice | registros que vencen en la ventana |
| `estado_fuente()` | ambas | latencia del portal + frescura/conteo del índice |

Estados: `VIGENTE` · `POR_VENCER` (≤`DIAS_ALERTA`, default 60) · `VENCIDO` · `SIN_REGISTRO` · `INDETERMINADO`. El booleano `vigente` gobierna bloqueos de alta/pago; `INDETERMINADO` nunca aprueba.

## 4. SLOs (medidos, no presupuestados)

| Métrica | v1.0 objetivo | v2.0 medido |
|---|---|---|
| Consulta puntual | <500 ms (índice) | ~800 ms (en vivo, dato fresco al segundo) |
| Confirmación de vigencia | <8 s (scraping) | misma consulta de arriba |
| Búsqueda en índice | — | <50 ms local |
| Frescura del índice | ≤24 h | ≤26 h (cron diario + rebuild-on-boot) |
| Import completo | — | ~8 s parse / ~155k filas |
| Cobertura | ~220k estimada | 155,558 filas reales del corte |

## 5. Despliegue

- **Render** (free, ohio, runtime python): web `repse-web` — landing `/`, `/health`, MCP Streamable HTTP en `/connect`, `/refresh` (bearer). `render.yaml` en la raíz.
- **Auth:** bearer estático (`MCP_API_KEY`) + OAuth WorkOS AuthKit opcional (`AUTHKIT_DOMAIN`+`BASE_URL`). El metadata OAuth se sirve **también en la raíz** (`/.well-known/oauth-protected-resource`) — fix preventivo del bug de discovery del connector de Claude (WE-399 en sat69). **No** registrar resource indicators en el entorno WorkOS compartido.
- **Landing** duplicada como Cloudflare Worker en `repse.watr.mx` (convención WATR).
- **stdio local:** `.venv/bin/repse-mcp` registrado en `~/.claude.json`.

## 6. Fuera de alcance

Inscripción/renovación ante STPS (e.firma del titular), validación cruzada directa SAT/IMSS/INFONAVIT (para SAT 69/69-B existe `sat69-mcp` como MCP hermano), interpretación jurídica, monitoreo con suscripciones/alertas (fase futura; `por_vencer` ya da la primitiva), listado de cancelados (ruta de descarga no encontrada aún).

## 7. Perfil legal

Datos públicos publicados por la STPS para consulta pública; el servicio los reexpone con atribución de fuente y sello de tiempo, se identifica por User-Agent, limita concurrencia (cortesía con el portal) y no emite constancias oficiales. La decisión legal/fiscal es del especialista.
