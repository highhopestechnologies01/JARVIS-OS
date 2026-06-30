/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/api/hermes/:path*",
        destination: `${process.env.NEXT_PUBLIC_HERMES_URL || "http://hermes:8000"}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
