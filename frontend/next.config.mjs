/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  // Proxy API calls to the FastAPI backend
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/:path*`,
      },
    ];
  },
};

export default nextConfig;
