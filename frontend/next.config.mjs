/** @type {import('next').NextConfig} */

// All browser -> data-layer traffic is proxied through Next so the app makes
// same-origin requests (no CORS) and the backend URL stays a server-side concern.
// 127.0.0.1 (not localhost) per the repo's Windows IPv6 gotcha (~2s/call on ::1).
const DATA_LAYER_BASE_URL =
  process.env.DATA_LAYER_BASE_URL || "http://127.0.0.1:8000";

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination: `${DATA_LAYER_BASE_URL}/:path*`,
      },
    ];
  },
};

export default nextConfig;
