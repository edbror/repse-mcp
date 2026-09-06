# El proveedor "tiene REPSE" — pero ¿está vigente, y para el servicio que le contrataste?

*Un servidor MCP que consulta en vivo el Padrón REPSE de la STPS y te dice tres cosas: si existe, si sigue vigente, y si su actividad autorizada cubre lo que le vas a pagar.*

Contratar servicios especializados en México sin verificar el REPSE es caro de una forma silenciosa: sin registro vigente, el contratante **pierde la deducción de IVA e ISR** de esas facturas y asume **responsabilidad solidaria** como patrón. Y la trampa fina es que "está en el padrón" no significa "está vigente" —ni "está autorizado para lo que le contrataste".

Por eso hicimos **REPSE MCP**: consulta el Padrón Público de Contratistas de Servicios Especializados u Obras Especializadas de la STPS **en vivo**, desde tu agente, tu ERP o tu flujo de alta de proveedores. Cada consulta va directo al padrón, así que el dato es de hoy, no de un índice que se quedó viejo.

## Qué te devuelve

- `verificar_repse` — RFC, folio o razón social → veredicto de vigencia **más** las actividades autorizadas.
- `verificar_lote` — tu cartera de proveedores → conteos y **sólo** los que requieren acción.
- `buscar_padron` — búsqueda por razón social cuando no tienes el RFC.

El estado es explícito: `VIGENTE`, `POR_VENCER` (≤60 días), `VENCIDO`, `SIN_REGISTRO` o `INDETERMINADO`. Un solo booleano, `vigente`, es el que debe gobernar un bloqueo de alta o de pago.

## Dos errores que evita

**Aprobar a un vencido.** El endpoint del padrón regresa "lo encontré" incluso para registros ya vencidos. Quien lee ese campo como si fuera vigencia da de alta proveedores vencidos. Nosotros calculamos la vigencia contra la fecha de vencimiento, no contra "aparece o no aparece".

**Pagar por un servicio no autorizado.** Un proveedor vigente para "limpieza industrial" **no** está autorizado para vigilancia. REPSE MCP te entrega las actividades autorizadas para que cruces que cubran el servicio que realmente contrataste.

## Lo que decimos de frente

**Informa; no emite la constancia.** No sustituye la constancia oficial ni la verificación directa en repse.stps.gob.mx, ni el criterio legal de tu área. Es la capa que te dice dónde mirar y qué bloquear, rápido y a escala.

**No estamos afiliados a la STPS.** Leemos su padrón público; no somos un canal oficial.

**Cruzar la actividad sigue siendo un juicio humano.** Te damos las actividades autorizadas tal como están en el padrón; que "instalaciones eléctricas" cubra o no el trabajo específico de tu contrato lo decide tu equipo.

## Es privado, para tu operación de compras

REPSE MCP no es una web pública: es un servidor MCP que se conecta a tu flujo de compras, alta de proveedores, due diligence o cuentas por pagar. Si en tu empresa nadie quiere ser el que aprobó el pago a un proveedor sin REPSE vigente, **escríbenos a ed@watr.mx y agendamos una demo**.
