'use client';

import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Search, ChevronRight, Filter, X } from 'lucide-react';
import Link from 'next/link';

// API Base URL
const API_BASE_URL = 'http://localhost:8000/api';

// Types
interface Brand {
    id: number;
    name: string;
    key: string;
}

interface Category {
    id: string;
    name: string;
}

interface Device {
    id: number;
    brand_id: number;
    name: string;
    main_image: string;
    release_at: string | null;
}

export default function Home() {
    // State
    const [searchQuery, setSearchQuery] = useState('');
    const [brands, setBrands] = useState<Brand[]>([]); // Used for search dropdown
    const [allBrands, setAllBrands] = useState<Brand[]>([]); // Used for main grid
    const [loadingBrands, setLoadingBrands] = useState(true);

    const [selectedBrand, setSelectedBrand] = useState<Brand | null>(null);

    const [categories, setCategories] = useState<Category[]>([]);
    const [selectedCategory, setSelectedCategory] = useState<string>('phones');

    // Storage Filter State
    const [selectedStorage, setSelectedStorage] = useState<string | null>(null);
    const [storageOptions, setStorageOptions] = useState<string[]>([]);
    const [showFilters, setShowFilters] = useState(false);

    const [devices, setDevices] = useState<Device[]>([]);
    const [loadingDevices, setLoadingDevices] = useState(false);

    // Initial Fetch: All Brands & Storage Options
    useEffect(() => {
        fetchAllBrands();
        fetchStorageOptions();
    }, []);

    const fetchStorageOptions = async () => {
        try {
            const res = await axios.get(`${API_BASE_URL}/filters/storage`);
            setStorageOptions(res.data);
        } catch (error) {
            console.error("Error fetching storage options", error);
        }
    };

    const fetchAllBrands = async () => {
        setLoadingBrands(true);
        try {
            const res = await axios.get(`${API_BASE_URL}/brands`);
            setAllBrands(res.data);
        } catch (error) {
            console.error("Error fetching all brands", error);
        } finally {
            setLoadingBrands(false);
        }
    };

    // Debounce Search for Dropdown
    useEffect(() => {
        const timeoutId = setTimeout(() => {
            if (searchQuery.length >= 1) {
                fetchSearchBrands(searchQuery);
            } else {
                setBrands([]);
            }
        }, 300);
        return () => clearTimeout(timeoutId);
    }, [searchQuery]);

    // Fetch Brands for Search Dropdown
    const fetchSearchBrands = async (query: string) => {
        try {
            const res = await axios.get(`${API_BASE_URL}/brands/search`, { params: { q: query } });
            setBrands(res.data);
        } catch (error) {
            console.error("Error searching brands", error);
        }
    };

    // Select Brand -> Fetch Categories & Default Devices
    const handleSelectBrand = async (brand: Brand) => {
        selectedBrandChange(brand);
    };

    const selectedBrandChange = async (brand: Brand) => {
        setSelectedBrand(brand);
        setSearchQuery('');
        setBrands([]); // Clear dropdown
        setSelectedStorage(null); // Reset filter
        setShowFilters(false); // Reset filter visibility

        // Fetch Categories
        try {
            const catRes = await axios.get(`${API_BASE_URL}/brands/${brand.id}/subcategories`);
            setCategories(catRes.data);

            // Default to first category or phones
            const defaultCat = catRes.data.length > 0 ? catRes.data[0].id : 'phones';
            setSelectedCategory(defaultCat);

            fetchDevices(brand.id, defaultCat, null);
        } catch (error) {
            console.error("Error fetching categories", error);
        }
    }

    // Fetch Devices
    const fetchDevices = async (brandId: number, type: string, storage: string | null) => {
        setLoadingDevices(true);
        try {
            const params: any = { brand_id: brandId, type };
            if (storage) {
                params.storage = storage;
            }
            const res = await axios.get(`${API_BASE_URL}/devices`, { params });
            setDevices(res.data);
        } catch (error) {
            console.error("Error fetching devices", error);
        } finally {
            setLoadingDevices(false);
        }
    };

    // Handle Category Change
    const handleCategoryChange = (catId: string) => {
        setSelectedCategory(catId);
        if (selectedBrand) {
            fetchDevices(selectedBrand.id, catId, selectedStorage);
        }
    };

    // Handle Storage Change
    const handleStorageChange = (storage: string) => {
        const newStorage = selectedStorage === storage ? null : storage;
        setSelectedStorage(newStorage);
        if (selectedBrand) {
            fetchDevices(selectedBrand.id, selectedCategory, newStorage);
        }
    };

    const handleBackToBrands = () => {
        setSelectedBrand(null);
        setCategories([]);
        setDevices([]);
    };

    return (
        <div className="min-h-screen bg-gray-50 text-gray-900 font-sans selection:bg-indigo-100 selection:text-indigo-900">

            {/* Header */}
            <header className="bg-white border-b border-gray-200 sticky top-0 z-30">
                <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-20 flex items-center justify-between">
                    <div
                        className="flex items-center gap-2 cursor-pointer"
                        onClick={handleBackToBrands}
                    >
                        <div className="w-8 h-8 bg-indigo-600 rounded-lg flex items-center justify-center text-white font-bold text-xl">M</div>
                        <h1 className="text-xl font-bold tracking-tight text-gray-900">Model<span className="text-indigo-600">Scraper</span></h1>
                    </div>

                    {/* Search Bar */}
                    <div className="relative w-full max-w-md hidden sm:block">
                        <div className="relative">
                            <input
                                type="text"
                                className="w-full pl-10 pr-4 py-2 bg-gray-100 border-none rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 transition-all font-medium"
                                placeholder="Search for a brand..."
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                            />
                            <Search className="absolute left-3.5 top-2.5 w-4 h-4 text-gray-400" />
                        </div>

                        {/* Search Dropdown */}
                        {brands.length > 0 && (
                            <div className="absolute top-full left-0 right-0 mt-2 bg-white rounded-xl shadow-xl border border-gray-100 overflow-hidden z-50 max-h-96 overflow-y-auto">
                                {brands.map((brand) => (
                                    <button
                                        key={brand.id}
                                        className="w-full text-left px-4 py-3 hover:bg-gray-50 flex items-center justify-between group transition-colors"
                                        onClick={() => handleSelectBrand(brand)}
                                    >
                                        <span className="font-medium text-gray-700 group-hover:text-indigo-600">{brand.name}</span>
                                        <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-indigo-600" />
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            </header>

            <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

                {!selectedBrand ? (
                    /* All Brands Grid */
                    <div className="animate-in fade-in duration-500">
                        <h2 className="text-3xl font-bold text-gray-900 mb-6">All Brands</h2>
                        {loadingBrands ? (
                            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                                {[...Array(12)].map((_, i) => (
                                    <div key={i} className="bg-white rounded-xl p-6 h-24 animate-pulse border border-gray-100"></div>
                                ))}
                            </div>
                        ) : (
                            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                                {allBrands.map((brand) => (
                                    <button
                                        key={brand.id}
                                        onClick={() => handleSelectBrand(brand)}
                                        className="bg-white hover:bg-indigo-50 border border-gray-200 hover:border-indigo-200 rounded-xl p-6 flex items-center justify-center font-semibold text-gray-700 hover:text-indigo-600 transition-all shadow-sm hover:shadow-md"
                                    >
                                        {brand.name}
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                ) : (
                    /* Selected Brand View */
                    <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
                        {/* Back Button */}
                        <button
                            onClick={handleBackToBrands}
                            className="mb-6 text-sm text-gray-500 hover:text-indigo-600 flex items-center gap-1 transition-colors"
                        >
                            &larr; Back to all brands
                        </button>

                        {/* Brand Header */}
                        <div className="mb-8">
                            <h2 className="text-4xl font-extrabold text-gray-900 tracking-tight mb-4">{selectedBrand.name}</h2>

                            {/* Category Tabs */}
                            <div className="flex flex-wrap gap-2 border-b border-gray-200 pb-1">
                                {categories.map((cat) => (
                                    <button
                                        key={cat.id}
                                        onClick={() => handleCategoryChange(cat.id)}
                                        className={`px-4 py-2 text-sm font-medium rounded-t-lg transition-all relative top-px 
                                    ${selectedCategory === cat.id
                                                ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/50'
                                                : 'text-gray-500 hover:text-gray-700 hover:bg-gray-50'}`}
                                    >
                                        {cat.name}
                                    </button>
                                ))}
                            </div>

                            {/* Filter Toggle */}
                            <div className="mt-4">
                                <button
                                    onClick={() => setShowFilters(true)}
                                    className="flex items-center gap-2 text-black font-semibold hover:text-gray-700 transition-colors uppercase tracking-wide text-sm border-b border-black pb-0.5"
                                >
                                    <span>Filter</span>
                                    <Filter className="w-4 h-4 ml-1" />
                                </button>
                            </div>
                        </div>

                        {/* Filter Sidebar */}
                        {showFilters && (
                            <>
                                {/* Overlay */}
                                <div
                                    className="fixed inset-0 bg-black/30 z-40 animate-in fade-in duration-200"
                                    onClick={() => setShowFilters(false)}
                                ></div>

                                {/* Sidebar Panel */}
                                <div className="fixed top-0 right-0 h-full w-80 bg-white z-50 shadow-2xl p-6 overflow-y-auto animate-in slide-in-from-right duration-300">
                                    <div className="flex items-center justify-between mb-8 border-b border-gray-100 pb-4">
                                        <h3 className="text-xl font-bold text-gray-900 tracking-wide uppercase">Filter</h3>
                                        <button
                                            onClick={() => setShowFilters(false)}
                                            className="p-2 hover:bg-gray-100 rounded-full transition-colors"
                                        >
                                            <X className="w-6 h-6 text-gray-500" />
                                        </button>
                                    </div>

                                    {/* Storage Section */}
                                    <div className="mb-6">
                                        <h4 className="text-lg font-bold text-gray-900 mb-4 border-b-2 border-black inline-block pb-1">Storage</h4>
                                        <div className="space-y-3">
                                            {storageOptions.map((storage) => (
                                                <label key={storage} className="flex items-center gap-3 cursor-pointer group">
                                                    <div className={`w-5 h-5 border-2 flex items-center justify-center transition-colors
                                                ${selectedStorage === storage
                                                            ? 'bg-black border-black'
                                                            : 'border-gray-300 group-hover:border-gray-400'
                                                        }`}
                                                    >
                                                        {selectedStorage === storage && <div className="w-2.5 h-2.5 bg-white"></div>}
                                                    </div>
                                                    <input
                                                        type="checkbox"
                                                        className="hidden"
                                                        checked={selectedStorage === storage}
                                                        onChange={() => handleStorageChange(storage)}
                                                    />
                                                    <span className={`text-base font-medium ${selectedStorage === storage ? 'text-black' : 'text-gray-600'}`}>
                                                        {storage}
                                                    </span>
                                                </label>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </>
                        )}

                        {/* Device Grid */}
                        {loadingDevices ? (
                            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-6">
                                {[...Array(10)].map((_, i) => (
                                    <div key={i} className="bg-white rounded-2xl p-4 h-64 animate-pulse border border-gray-100">
                                        <div className="w-full h-32 bg-gray-200 rounded-lg mb-4"></div>
                                        <div className="h-4 bg-gray-200 rounded w-3/4 mb-2"></div>
                                        <div className="h-3 bg-gray-200 rounded w-1/2"></div>
                                    </div>
                                ))}
                            </div>
                        ) : devices.length === 0 ? (
                            <div className="py-20 text-center text-gray-500">
                                No devices found in this category.
                            </div>
                        ) : (
                            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-6 animate-in fade-in duration-700">
                                {devices.map((device) => (
                                    <Link
                                        href={`/device/${device.id}${selectedStorage ? `?highlight=${selectedStorage}` : ''}`}
                                        key={device.id}
                                        className="group bg-white rounded-2xl p-4 border border-gray-100 hover:border-indigo-100 hover:shadow-xl hover:shadow-indigo-500/10 transition-all cursor-pointer flex flex-col items-center text-center relative overflow-hidden"
                                    >
                                        <div className="w-full h-40 mb-4 relative flex items-center justify-center bg-gray-50 rounded-xl group-hover:bg-white transition-colors">
                                            <img
                                                src={device.main_image}
                                                alt={device.name}
                                                className="max-h-full max-w-full object-contain mix-blend-multiply group-hover:scale-110 transition-transform duration-500"
                                                onError={(e) => {
                                                    (e.target as HTMLImageElement).src = 'https://placehold.co/200x200/f3f4f6/a3a3a3?text=No+Image';
                                                }}
                                            />
                                        </div>
                                        <h3 className="font-semibold text-gray-900 group-hover:text-indigo-600 transition-colors line-clamp-2">{device.name}</h3>
                                        {device.release_at && (
                                            <p className="text-xs text-gray-400 mt-1">{device.release_at}</p>
                                        )}
                                    </Link>
                                ))}
                            </div>
                        )}
                    </div>
                )}
            </main>
        </div>
    );
}
