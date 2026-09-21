import { NextRequest, NextResponse } from "next/server";

// Proxy same-origin para /api, /webhook e /health -> API FastAPI.
//
// Usa Middleware (não next.config.js rewrites) porque rewrites() é
// resolvido em build time — o valor de API_PROXY_TARGET definido no
// docker-compose (ex: http://api:8000) só existe em runtime, dentro do
// container. Middleware roda por request e lê process.env a cada chamada.
const API_PROXY_TARGET = process.env.API_PROXY_TARGET || "http://localhost:8000";

export function middleware(request: NextRequest) {
  const target = new URL(
    request.nextUrl.pathname + request.nextUrl.search,
    API_PROXY_TARGET,
  );
  return NextResponse.rewrite(target);
}

export const config = {
  matcher: ["/api/:path*", "/webhook/:path*", "/health"],
};
