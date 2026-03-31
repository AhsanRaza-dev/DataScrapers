'use client';

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, Info, Calendar } from 'lucide-react';
import Link from 'next/link';

// API Base URL
const API_BASE_URL = 'http://localhost:8000/api';

interface DeviceDetails {
    id: number;
    brand_id: number;
    name: string;
    main_image: string;
    release_at: string | null;
    specifications: Record<string, { key: string; value: string }[]>;
}

const EXCLUDED_CATEGORIES = [
    'EU LABEL',
    'Our Tests',
    'Battery',
    'Features',
    'Comms',
    'Sound',
    'Selfie camera',
    'Main Camera',
    'Display',
    'Body',
    'Network'
];

export default function DevicePage() {
    const params = useParams();
    const router = useRouter();
    const searchParams = useSearchParams();
    const highlight = searchParams.get('highlight');
    const { id } = params;

    const [device, setDevice] = useState<DeviceDetails | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');

    useEffect(() => {
        if (id) {
            fetchDeviceDetails(id as string);
        }
    }, [id]);

    const fetchDeviceDetails = async (deviceId: string) => {
        setLoading(true);
        try {
            const res = await axios.get(`${API_BASE_URL}/devices/${deviceId}`);
            setDevice(res.data);
        } catch (err) {
            console.error("Error fetching device details", err);
            setError('Failed to load device details.');
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="flex flex-col items-center">
                    <div className="w-12 h-12 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin mb-4"></div>
                    <p className="text-gray-500 font-medium">Loading device details...</p>
                </div>
            </div>
        );
    }

    if (error || !device) {
        return (
            <div className="min-h-screen bg-gray-50 flex items-center justify-center">
                <div className="text-center">
                    <h2 className="text-2xl font-bold text-gray-900 mb-2">Device Not Found</h2>
                    <p className="text-gray-500 mb-6">{error || "The requested device could not be found."}</p>
                    <Link href="/" className="px-6 py-3 bg-indigo-600 text-white font-medium rounded-xl hover:bg-indigo-700 transition-colors">
                        Return Home
                    </Link>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gray-50 font-sans text-gray-900 selection:bg-indigo-100 selection:text-indigo-900 pb-20">

            {/* Navbar */}
            <nav className="bg-white border-b border-gray-200 sticky top-0 z-30">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center gap-4">
                    <Link href="/" className="p-2 -ml-2 hover:bg-gray-100 rounded-full transition-colors text-gray-600">
                        <ArrowLeft className="w-5 h-5" />
                    </Link>
                    <h1 className="text-lg font-bold text-gray-900 truncate">{device.name}</h1>
                </div>
            </nav>

            <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                <div className="flex flex-col lg:flex-row gap-8 bg-white rounded-3xl overflow-hidden shadow-sm border border-gray-100">

                    {/* Left Column: Image & Basic Info */}
                    <div className="w-full lg:w-1/3 bg-gray-50/50 p-8 flex flex-col items-center border-b lg:border-b-0 lg:border-r border-gray-100">
                        <div className="w-full aspect-square flex items-center justify-center bg-white rounded-2xl p-6 mb-8 shadow-sm border border-gray-100">
                            <img
                                src={device.main_image}
                                alt={device.name}
                                className="max-h-full max-w-full object-contain mix-blend-multiply"
                                onError={(e) => {
                                    (e.target as HTMLImageElement).src = 'https://placehold.co/400x400/f3f4f6/a3a3a3?text=No+Image';
                                }}
                            />
                        </div>

                        <h1 className="text-3xl font-extrabold text-center text-gray-900 mb-3">{device.name}</h1>

                        {device.release_at && (
                            <div className="flex items-center gap-2 px-4 py-2 bg-indigo-50 border border-indigo-100 rounded-full text-indigo-700 font-medium text-sm">
                                <Calendar className="w-4 h-4" />
                                <span>Released: {device.release_at}</span>
                            </div>
                        )}
                    </div>

                    {/* Right Column: Specifications */}
                    <div className="w-full lg:w-2/3 p-8">
                        <div className="flex items-center gap-3 mb-6 pb-4 border-b border-gray-100">
                            <div className="w-10 h-10 bg-indigo-100 rounded-xl flex items-center justify-center text-indigo-600">
                                <Info className="w-5 h-5" />
                            </div>
                            <div>
                                <h2 className="text-xl font-bold text-gray-900">Technical Specifications</h2>
                                <p className="text-sm text-gray-500">Detailed hardware and software specs</p>
                            </div>
                        </div>

                        <div className="space-y-8">
                            {Object.entries(device.specifications)
                                .filter(([category]) => !EXCLUDED_CATEGORIES.includes(category))
                                .sort(([a], [b]) => {
                                    const priority = ['Misc', 'Memory', 'Launch'];
                                    const idxA = priority.indexOf(a);
                                    const idxB = priority.indexOf(b);

                                    if (idxA !== -1 && idxB !== -1) return idxA - idxB; // Both in priority list: sort by index
                                    if (idxA !== -1) return -1; // Only A in priority: A comes first
                                    if (idxB !== -1) return 1;  // Only B in priority: B comes first
                                    return 0; // neither in priority: keep original order
                                })
                                .map(([category, specs]) => (
                                    <div key={category} className="bg-gray-50/50 rounded-2xl p-6 border border-gray-100">
                                        <h3 className="text-sm font-bold text-indigo-600 uppercase tracking-wider mb-4 flex items-center gap-2">
                                            {category === 'Misc' ? 'Price / Misc' : category}
                                        </h3>
                                        <dl className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-4">
                                            {specs.map((spec, idx) => {
                                                // Split spec by comma to handle multiple variants
                                                const parts = spec.value.split(',').map(p => p.trim());

                                                // If highlight is active, filter parts to only show matching ones
                                                // Otherwise show all parts
                                                const validParts = highlight
                                                    ? parts.filter(p => p.toLowerCase().includes(highlight.toLowerCase()))
                                                    : parts;

                                                // If filtering resulted in no matches (unexpected), fallback to all
                                                const displayParts = validParts.length > 0 ? validParts : parts;

                                                return (
                                                    <div key={idx} className="flex flex-col border-b border-gray-200/50 last:border-0 pb-2 last:pb-0">
                                                        <dt className="text-xs font-semibold text-gray-500 uppercase mb-1">{spec.key}</dt>
                                                        <dd className="text-sm font-medium text-gray-900 leading-relaxed">
                                                            {displayParts.map((part, i) => (
                                                                <div key={i} className={i > 0 ? 'mt-1' : ''}>
                                                                    {highlight && part.toLowerCase().includes(highlight.toLowerCase()) ? (
                                                                        <span>
                                                                            {part.split(new RegExp(`(${highlight})`, 'gi')).map((subPart, j) =>
                                                                                subPart.toLowerCase() === highlight.toLowerCase() ? (
                                                                                    <span key={j} className="bg-red-100 text-red-700 font-bold px-1 rounded mx-0.5 border border-red-200">
                                                                                        {subPart}
                                                                                    </span>
                                                                                ) : (
                                                                                    <span key={j} className="text-gray-600">{subPart}</span>
                                                                                )
                                                                            )}
                                                                        </span>
                                                                    ) : (
                                                                        part
                                                                    )}
                                                                </div>
                                                            ))}
                                                        </dd>
                                                    </div>
                                                );
                                            })}
                                        </dl>
                                    </div>
                                ))}
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
}
