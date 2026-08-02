# PLAN — repse-mcp

Linear: [WE-493](https://linear.app/we-are-the-robots-inc/issue/WE-493/repse-mcp-mcp-de-consulta-repse-padron-stps)
Spec original: `SPEC_MCP_REPSE.md` (v1.0 draft, 15-jul-2026)

## Cambio de arquitectura vs. la spec

La spec v1.0 partía de que **"REPSE no ofrece API oficial → toda la ingesta se resuelve por descarga del padrón + automatización del portal"**, y de ahí derivaba un índice propio, scraping headless y una frescura de ≤24 h.

Verificado contra el portal el **2026-08-01**, eso no aplica:

- `repse.stps.gob.mx/Publico` (la ruta que cita la spec) hoy da **404**.
- El portal actual es un Laravel cuyo bundle JS llama a **dos endpoints JSON públicos, sin auth**: `busca_razon_social` (typeahead por RFC/folio/razón social) y `buscar-padron` (detalle + actividades).
- Latencia medida extremo a extremo: **~770 ms**, contra los 8 s p95 que la spec presupuestaba para scraping.

Consecuencia: **sin base de datos, sin Turso, sin pipeline de ingesta, sin navegador headless.** La frescura pasa de "≤24 h" a "en vivo". Se elimina la mitad de la infraestructura que la spec asumía y todo el riesgo de índice viejo (que es exactamente lo que mordió a sat69 con la URL congelada del 69-B).

## Fase 1 — MVP en vivo ✅

- [x] Cliente HTTP con sesión + CSRF y renovación ante 419 (`client.py`)
- [x] Veredicto determinista de vigencia (`risk.py`) — incluida la trampa de `registro: 1` en registros vencidos
- [x] Resolución término → registro con verificación de RFC (`consulta.py`)
- [x] Tools: `verificar_repse`, `verificar_lote`, `buscar_padron`, `estado_fuente`
- [x] Tests (13) + ruff + CI en PR
- [x] Landing de venta en `/`, `/health`, MCP en `/connect`
- [x] Deploy en Render + `repse.watr.mx` (Cloudflare Worker)

## Fase 2 — Índice local ✅ (2026-08-02)

Se adelantó: la descarga existe y es pública — `GET /padron-public-excel` (xlsx ~26 MB, 155,558 filas, SIN columna RFC). Implementado en `padron.py`: SQLite+FTS5, rebuild-on-boot **sin Turso** (la fuente parsea en ~8 s; Turso queda como fallback si la STPS bloquea datacenter), guards de frescura, `/refresh` + cron diario en Actions. Tools: `buscar_padron` local paginado y `por_vencer`. Ver `SPEC.md` v2.

## Fase 3 — sólo si el uso lo pide

- **Monitoreo de portafolio con alertas** (suscripciones). `por_vencer` ya da la primitiva; falta sólo la capa de suscripción+notificación. Cron en Actions → endpoint en Render (nunca workers pagados).
- **Cruce con sat69-mcp.** Un proveedor REPSE-vigente que sea EFOS definitivo sigue siendo un "no". El cruce de mayor valor y el más barato: ambos MCP ya existen.
- **Resumen de cartera con IA.** Sólo la narrativa; el veredicto se queda determinista, como en sat69.
- **Listado de cancelados.** La ruta de descarga no apareció (variantes de `padron-public-excel` dan 404); buscar oportunísticamente.

## Fuera de alcance (confirmado)

Inscripción/renovación ante la STPS (exige e.firma del titular), validación directa con SAT/IMSS/INFONAVIT, e interpretación jurídica del cumplimiento.
