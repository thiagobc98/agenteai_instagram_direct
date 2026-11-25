/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  experimental: {
    // O proxy de /api (middleware.ts) corta o corpo da requisição em 10 MB
    // por padrão: uploads de vídeo (Reels) chegariam truncados à API.
    middlewareClientMaxBodySize: "300mb",
  },
};

module.exports = nextConfig;
