// repse.watr.mx — sirve la landing estática, pero proxya el MCP a Render para
// que el servidor viva bajo el dominio de marca y no exponga el onrender.com
// crudo en el registro oficial de MCP (WE-1143).
//
// Se proxya SÓLO lo público del protocolo:
//   • /connect            → endpoint MCP (streamable-HTTP)
//   • /.well-known/oauth* → discovery de OAuth (AuthKit)
// Los endpoints de administración NO se exponen aquí y quedan sólo en onrender
// tras el bearer: /refresh (reconstruye el índice), /verificar y
// /verificar-lote (los consume MATERIA con MCP_API_KEY), y /health.
//
// ponytail: proxy por prefijo; la Response se devuelve tal cual, así el SSE de
// streamable-HTTP pasa directo. fetch() fija el Host desde la URL destino, que
// es lo que hace que Render enrute bien.
//
// Calcado de sat69-mcp/landing/src/worker.js, que lleva meses en producción.
const ORIGIN = "https://repse-mcp.onrender.com";

export default {
  async fetch(request, env) {
    const { pathname, search } = new URL(request.url);
    const proxied =
      pathname === "/connect" ||
      pathname.startsWith("/connect/") ||
      pathname.startsWith("/.well-known/oauth");
    if (proxied) {
      return fetch(new Request(ORIGIN + pathname + search, request));
    }
    return env.ASSETS.fetch(request);
  },
};
