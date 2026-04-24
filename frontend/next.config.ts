import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "**.flipp.com" },
      { protocol: "https", hostname: "**.flippback.com" },
      { protocol: "https", hostname: "**.wishabi.net" },
      { protocol: "https", hostname: "**.heb.com" },
      { protocol: "https", hostname: "**.kroger.com" },
      { protocol: "https", hostname: "**.walmart.com" },
      { protocol: "https", hostname: "**.walmartimages.com" },
      { protocol: "https", hostname: "**.scene7.com" },
      { protocol: "https", hostname: "**.target.com" },
      { protocol: "https", hostname: "**.samsclub.com" },
      { protocol: "https", hostname: "**.costco.com" },
      { protocol: "https", hostname: "**.instacart.com" },
      { protocol: "https", hostname: "**.gstatic.com" },
      { protocol: "https", hostname: "**.amazonaws.com" },
      { protocol: "https", hostname: "**.cloudfront.net" },
    ],
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${process.env.NEXT_PUBLIC_API_URL}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
