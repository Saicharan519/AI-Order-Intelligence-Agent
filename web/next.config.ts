import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // No floating Next.js badge while developing (it never appears in production builds);
  // compile and runtime errors are still shown.
  devIndicators: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
