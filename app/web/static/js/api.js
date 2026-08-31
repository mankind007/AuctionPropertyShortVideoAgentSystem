/** 统一 API 封装：自动附加 Bearer token、统一错误处理。 */
class ApiClient {
    constructor() {
        this.token = localStorage.getItem('token') || null;
    }

    setToken(token) {
        this.token = token;
        if (token) localStorage.setItem('token', token);
        else localStorage.removeItem('token');
    }

    clearToken() {
        this.token = null;
        localStorage.removeItem('token');
    }

    async request(path, options = {}) {
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers,
        };
        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        // path 传入完整路径（如 /api/materials），不再拼接前缀
        const res = await fetch(path, {
            ...options,
            headers,
        });

        if (res.status === 401) {
            this.clearToken();
            window.location.href = '/login';
            throw new Error('登录已过期，请重新登录');
        }

        if (!res.ok) {
            let msg = `请求失败 (${res.status})`;
            try {
                const err = await res.json();
                if (typeof err.detail === 'string') msg = err.detail;
                else if (err.detail) msg = JSON.stringify(err.detail);
                else if (err.message) msg = err.message;
            } catch {}
            throw new Error(msg);
        }

        if (res.status === 204) return null;
        return res.json();
    }

    get(path) { return this.request(path); }
    post(path, data) { return this.request(path, { method: 'POST', body: JSON.stringify(data) }); }
    put(path, data) { return this.request(path, { method: 'PUT', body: JSON.stringify(data) }); }
    patch(path, data) { return this.request(path, { method: 'PATCH', body: JSON.stringify(data) }); }
    delete(path) { return this.request(path, { method: 'DELETE' }); }
}

const api = new ApiClient();