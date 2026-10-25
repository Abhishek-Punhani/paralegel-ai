/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    const backend = (process.env.BACKEND_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
    return [
      { source: '/api/session/:path*', destination: `${backend}/api/session/:path*` },
      { source: '/api/voice/:path*', destination: `${backend}/api/voice/:path*` },
      { source: '/api/notifications/:path*', destination: `${backend}/api/notifications/:path*` },
      { source: '/api/upload-document', destination: `${backend}/api/upload-document` },
      { source: '/api/tool-call', destination: `${backend}/api/tool-call` },
      { source: '/health', destination: `${backend}/health` },
    ]
  },
  // Resolve @google/genai to its browser-compatible web build
  webpack: (config, { isServer }) => {
    if (!isServer) {
      // Tell webpack to use the 'browser' condition for @google/genai
      config.resolve.conditionNames = ["browser", "module", "import", "require", "default"];
    }
    return config;
  },
};

module.exports = nextConfig;
