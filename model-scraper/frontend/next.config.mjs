/** @type {import('next').NextConfig} */
const nextConfig = {
    images: {
        remotePatterns: [
            {
                protocol: 'https',
                hostname: 'placehold.co',
            },
            {
                protocol: 'https',
                hostname: 'aws-1-ap-southeast-1.pooler.supabase.com', // Just in case, though likely data urls or other
            },
        ],
    },
};

export default nextConfig;
