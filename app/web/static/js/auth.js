/** 认证相关：登录表单提交、token 存储/刷新、登出、路由守卫。 */
// 登录页逻辑
if (document.getElementById('login-form')) {
    document.getElementById('login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const data = new FormData(form);
        const errorDiv = document.getElementById('login-error');
        errorDiv.style.display = 'none';

        try {
            const res = await fetch('/api/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams(data).toString(),
            });
            if (!res.ok) {
                const err = await res.json();
                throw new Error(err.detail || '登录失败');
            }
            const { access_token } = await res.json();
            api.setToken(access_token);
            window.location.href = '/';
        } catch (err) {
            errorDiv.textContent = err.message;
            errorDiv.style.display = 'block';
        }
    });
}

// 全局登出处理
document.addEventListener('click', (e) => {
    if (e.target.id === 'logout-btn') {
        e.preventDefault();
        api.clearToken();
        window.location.href = '/login';
    }
});

// 路由守卫：未登录重定向到登录页
const publicPaths = ['/login', '/api/auth/login', '/api/auth/refresh'];
function checkAuth() {
    const path = window.location.pathname;
    if (publicPaths.includes(path)) return;
    if (!api.token && !publicPaths.includes(path)) {
        window.location.href = '/login';
    }
}

// 页面加载时检查
document.addEventListener('DOMContentLoaded', checkAuth);

// 定期刷新 token（可选）
setInterval(async () => {
    if (api.token) {
        try {
            await api.post('/api/auth/refresh');
        } catch {
            // 刷新失败会在 request 中处理重定向
        }
    }
}, 30 * 60 * 1000); // 30 分钟