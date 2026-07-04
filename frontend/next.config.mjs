/** @type {import('next').NextConfig} */
const nextConfig = {
  // Let Google Sign-In's popup post the credential back to us (fixes the
  // "Cross-Origin-Opener-Policy would block window.postMessage" warning).
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Cross-Origin-Opener-Policy", value: "same-origin-allow-popups" },
        ],
      },
    ];
  },
};
export default nextConfig;
