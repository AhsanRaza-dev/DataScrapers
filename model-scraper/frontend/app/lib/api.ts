import axios from 'axios';

const API_URL = 'http://localhost:8000/api';

const api = axios.create({
    baseURL: API_URL,
});

export const searchBrands = async (query: string) => {
    const response = await api.get(`/brands/search?q=${query}`);
    return response.data;
};

export const getSubcategories = async (brandId: number) => {
    const response = await api.get(`/brands/${brandId}/subcategories`);
    return response.data;
};

export const getDevices = async (brandId: number, type: string) => {
    const response = await api.get(`/devices?brand_id=${brandId}&type=${type}`);
    return response.data;
};

export const getDeviceDetails = async (deviceId: number) => {
    const response = await api.get(`/devices/${deviceId}`);
    return response.data;
};
