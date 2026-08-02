# repse-mcp

MCP server para consultar el **Padrón Público de Contratistas de Servicios Especializados u Obras Especializadas (REPSE)** de la STPS, en vivo, desde cualquier cliente MCP (Claude Desktop, Claude Code, Cowork, apps propias).

Convierte una verificación manual —entrar al portal, capturar RFC por RFC, interpretar el resultado— en una capacidad programática de cumplimiento para compras, alta de proveedores, due diligence y cuentas por pagar.

Hermano de [`sat69-mcp`](https://github.com/edbror/sat69-mcp) (listas SAT 69/69-B). Se complementan: un proveedor con REPSE vigente que además es EFOS definitivo sigue siendo un "no".

## Tools

| Tool | Qué hace |
|---|---|
| `verificar_repse(termino)` | RFC, folio o razón social → veredicto de vigencia + actividades autorizadas |
| `verificar_lote(rfcs)` | Cartera de proveedores → conteos y **sólo** los que requieren acción |
| `buscar_padron(texto)` | Búsqueda por razón social en el padrón |
| `estado_fuente()` | Disponibilidad y latencia del portal de la STPS |

Estados: `VIGENTE` · `POR_VENCER` (≤60 días, configurable) · `VENCIDO` · `SIN_REGISTRO` · `INDETERMINADO`.
El booleano `vigente` es el que debe gobernar un bloqueo de alta o de pago.

## Arquitectura: en vivo, sin índice

El portal de la STPS **no requiere scraping de HTML**. Su bundle JS llama a dos endpoints JSON públicos y sin autenticación:

```
GET  /busca_razon_social?term=…          → [{id, text}]   (RFC, folio o razón social)
POST /buscar-padron   razon_social=<id>  → detalle + actividades autorizadas
```

`buscar-padron` es POST de Laravel: exige cookie de sesión + `X-CSRF-TOKEN`, que el cliente toma del `<meta csrf-token>` del home y renueva solo ante un 419.

Consecuencia: **no hay base de datos, ni Turso, ni pipeline de ingesta, ni navegador headless.** Cada consulta va en vivo al padrón, así que la frescura del dato es total y no hay índice que se quede viejo. Se paga con latencia (~1 s) en vez de infraestructura.

> Un índice local sólo se justifica si hace falta búsqueda masiva sobre todo el padrón o monitoreo de vencimientos — ver `PLAN.md` fase 2.

### La trampa del campo `registro`

`buscar-padron` devuelve `registro: 1` para registros **ya vencidos**: significa "lo encontré en el padrón", no "está vigente". Verificado contra el portal el 2026-08-01: el RFC `ASE100712TT2` regresa `registro: 1` con `fecha_vencimiento_registro: 2024-09-10`.

Quien lea `registro` como vigencia aprueba proveedores vencidos. La vigencia se calcula aquí, contra la fecha de vencimiento (`src/repse/risk.py`, cubierto en `tests/test_risk.py`).

## Uso local (stdio)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/repse-mcp          # stdio
.venv/bin/pytest -q          # tests
```

Registro en Claude Code (scope user, editando `~/.claude.json` directamente):

```json
"repse": {
  "command": "/Users/ed/mcp-servers/repse-mcp/.venv/bin/repse-mcp"
}
```

## Despliegue (Render)

`render.yaml` en la raíz. Runtime Python nativo, plan free, health check en `/health`, MCP en `/connect`, landing de venta en `/`.

Variables: `MCP_API_KEY` (bearer estático), `AUTHKIT_DOMAIN` + `BASE_URL` (OAuth WorkOS, opcional), `REPSE_BASE_URL` (override de fuente).

## Aviso

Esta herramienta informa; **no** emite la constancia oficial ni sustituye la verificación directa en [repse.stps.gob.mx](https://repse.stps.gob.mx/) ni el criterio legal. No afiliado a la STPS.
