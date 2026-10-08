# ESTADO — repse-mcp

> Medido el 2026-10-08 contra disco, GitHub y la API de Render.
> **Lo de abajo caduca.** Si esta fecha ya está vieja, no te creas el contenido:
> vuelve a medirlo con los comandos del final.

## Qué es

Servidor MCP sobre el Padrón Público de Contratistas de Servicios Especializados
(REPSE) de la STPS, consultado **en vivo**. Convierte una verificación manual
—entrar al portal, capturar RFC por RFC— en una capacidad programática.

**Qué no es:** no sustituye la constancia oficial ni el criterio legal.

## Para quién

Lo mismo que sat69: compras, alta de proveedores, due diligence, cuentas por
pagar. Son hermanos y se complementan — un proveedor con REPSE vigente que
además es EFOS definitivo sigue siendo un "no".

## Madurez, quién paga y de qué depende

> Escala común a los siete proyectos, para que se puedan comparar:
> **idea** (spec sin código) · **cimiento** (corre, no le sirve a nadie aún) ·
> **usable** (alguien podría usarlo hoy) · **en uso** (alguien lo usa de verdad) ·
> **terminado** (hace lo que prometió; no crece salvo que el uso lo pida).

| | |
|---|---|
| **Madurez** | **terminado**. Cero pendientes; su Fase 4 dice «sólo si el uso lo pide». |
| **Quién paga** | Nadie. |
| **De qué depende** | El portal de la STPS, consultado en vivo. sat69, para el cruce. |
| **Qué depende de él** | Nadie hoy. El spec de MATERIA lo promete y no lo usa. |

## Dónde vive

- Repo: `edbror/repse-mcp` · local: `~/mcp-servers/repse-mcp`
- Servicio: `repse-mcp` en Render, free, **fuera del cron de hibernación**
- Ojo: `Summer Projects/REPSia MCP` sólo tiene el spec original de agosto. Ese
  spec ya se construyó y es este repo. No es un pendiente.

## En qué estado está

Funcionando. Ocho archivos de prueba. Devuelve `vigente` como booleano para
decidir, y `estado` para distinguir VIGENTE / POR_VENCER / VENCIDO /
SIN_REGISTRO / INDETERMINADO.

Un detalle que importa y está resuelto: distingue el índice reconstruyéndose de
"no hay nada por vencer". Son cosas distintas y confundirlas da un falso verde.

## Qué lo bloquea

Nada. Terminado para lo que hace.

## Cómo volver a medir esto

```bash
pytest -q
curl -s https://repse-mcp.onrender.com/health
```
