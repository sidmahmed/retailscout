/** @type {import('next').NextConfig} */
const nextConfig = {
  // Local dev: proxy API calls to the FastAPI dev server so the browser
  // talks same-origin, matching the production shape on Vercel.
  async rewrites() {
    const api = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
    return [{ source: "/api/v1/:path*", destination: `${api}/api/v1/:path*` }];
  },
};

export default nextConfig;
