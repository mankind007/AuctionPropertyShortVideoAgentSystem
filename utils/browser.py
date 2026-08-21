"""跨技能共享的浏览器反检测常量与注入脚本(带类型注解)。

公拍网(gpai)与阿里资产(ali)爬虫共用的 User-Agent、启动参数与反检测注入 JS。
UA 在 `BROWSER_PROFILES` 池中轮换(每次浏览器启动前 `get_profile()` 随机取一个),
避免单一指纹重复,降低服务端识别关联度。
"""
from __future__ import annotations

import random


# 默认 UA(各调用方仍可直接用 `UA` 保持向后兼容,如 image download)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 浏览器指纹池: 不同 Chrome 大版本 + 硬件组合,每次浏览器启动前随机取一条。
# 每条仅含 UA +对应硬件参数;STEALTH_SCRIPT 其它 patch(插件/Canvas/WebGL/音频)保持一致。
BROWSER_PROFILES: list[dict] = [
    {"ua": UA, "cores": 8, "mem": 8, "gpu_vendor": "Intel Inc.", "gpu_renderer": "Intel GPU"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
     "cores": 6, "mem": 8, "gpu_vendor": "Intel Inc.", "gpu_renderer": "Intel GPU"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
     "cores": 12, "mem": 16, "gpu_vendor": "NVIDIA Corporation", "gpu_renderer": "NVIDIA GeForce GTX 1660"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
     "cores": 4, "mem": 4, "gpu_vendor": "Intel Inc.", "gpu_renderer": "Intel(R) UHD Graphics 620"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
     "cores": 8, "mem": 16, "gpu_vendor": "AMD", "gpu_renderer": "AMD Radeon(TM) Graphics"},
    {"ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
     "cores": 16, "mem": 32, "gpu_vendor": "NVIDIA Corporation", "gpu_renderer": "NVIDIA GeForce RTX 3060"},
]


def get_profile() -> dict:
    """从池中随机取一个浏览器指纹(UA+硬件),每次浏览器 launch 前调用。"""
    return random.choice(BROWSER_PROFILES)


# 反自动化识别: 关闭 automation 特性并去掉 playwright 默认识别的 --enable-automation
LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
    "--lang=zh-CN",
    "--window-size=1366,900",
    "--disable-features=Translate",
]

# 反检测注入脚本模板(L1-L4): 页面加载前注入,patch 所有已知 CDP 泄漏点。
# %UA%/%CORES%/%MEM%/%GPU_VENDOR%/%GPU_RENDERER% 由 render_stealth_script 渲染。
# 固定微噪(非每次随机)以保证同会话内 Canvas/WebGL 指纹稳定,避免触发风控。
_STEALTH_TEMPLATE: str = """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => false, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'plugins', {
      get: () => {
        const make = (name) => ({
          name, filename: 'internal-' + name + '.dll',
          description: 'Portable Document Format', length: 1,
          item: (i) => make(name), namedItem: () => make(name), refresh: () => {},
        });
        return [make('Chrome PDF Plugin'), make('Chrome PDF Viewer')];
      }, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'mimeTypes', {
      get: () => {
        const mt = (type, desc, suffixes, plugin) => ({
          type, description: desc, suffixes, enabledPlugin: plugin,
        });
        return [mt('application/pdf', 'Portable Document Format', 'pdf', {})];
      }, configurable: true, enumerable: true,
    });
    window.chrome = { runtime: {}, app: {}, loadTimes: function(){}, csi: function(){}, symbolicNames: function(){} };
    Object.defineProperty(navigator, 'languages', {
      get: () => ['zh-CN', 'zh', 'en-US', 'en', 'zh-TW'], configurable: true, enumerable: true,
    });
    // navigator.platform patch(默认不启用,%PLATFORM_PATCH%)
    %PLATFORM_PATCH%
    Object.defineProperty(navigator, 'hardwareConcurrency', {
      get: () => %CORES%, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'deviceMemory', {
      get: () => %MEM%, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'maxTouchPoints', {
      get: () => 0, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'vendor', {
      get: () => 'Google Inc.', configurable: true, enumerable: true,
    });
    // navigator.userAgent patch(默认不启用,%UA_PATCH%)
    %UA_PATCH%
    const uaData = {
      brands: [
        { brand: 'Chromium', version: '%CHROME_MAJOR%' },
        { brand: 'Google Chrome', version: '%CHROME_MAJOR%' },
        { brand: 'Not?A_Brand', version: '24' },
      ],
      mobile: false, platform: 'Windows',
    };
    try {
      Object.defineProperty(navigator, 'userAgentData', {
        get: () => uaData, configurable: true, enumerable: true,
      });
    } catch (e) {}
    if (window.Permissions && window.Permissions.prototype) {
      const origQuery = window.Permissions.prototype.query;
      window.Permissions.prototype.query = function(query) {
        if (query && query.name === 'notifications') {
          return Promise.resolve({ state: 'denied' });
        }
        return origQuery.call(this, query);
      };
    }
    // Canvas 指纹微噪(默认不启用,%CANVAS_PATCH%)
    %CANVAS_PATCH%
    // WebGL 指纹: 返回常见 GPU 字符串(%GPU_VENDOR% / %GPU_RENDERER%)
    try {
      const glProto = WebGLRenderingContext.prototype;
      const origGetParam = glProto.getParameter;
      glProto.getParameter = function(idx) {
        const DEBUG = 37446; // UNPLACED=WEBGL_debug_renderer_info
        if (idx === 37445 || idx === 37446) {
          if (idx === 37446) return '%GPU_VENDOR%';
          return '%GPU_RENDERER%';
        }
        try { return origGetParam.call(this, idx); } catch (e) { return null; }
      };
      if (!window.WebGLDebugRendererInfo) {
        window.WebGLDebugRendererInfo = {
          UNMASKED_VENDOR_WEBGL: 37445, UNMASKED_RENDERER_WEBGL: 37446,
        };
      }
    } catch (e) {}
    // AudioContext 指纹: 微调 getChannelData (固定微噪)
    try {
      if (window.AudioContext) {
        const origGC = AudioBuffer.prototype.getChannelData;
        AudioBuffer.prototype.getChannelData = function(ch) {
          const d = origGC.call(this, ch);
          const n = d.length;
          for (let i = 0; i < n; i += 256) {
            d[i] = (d[i] + 1e-6) % 1;
          }
          return d;
        };
      }
    } catch (e) {}
    // 删除 CDP / playwright 泄露变量(默认不启用,由 %CDP_CLEANUP% 按需注入)
    %CDP_CLEANUP%
  } catch (e) {}
})();
"""

# CDP 泄露变量清理代码: 默认不注入(部分站点会检测 chrome 对象是否被删除反而更可疑),
# 仅在 render_stealth_script(clean_cdp=True) 时启用。
_CDP_CLEANUP_JS: str = """
    try { delete window.cdc_ado; } catch (e) {}
    try { delete window.cdc_scripting; } catch (e) {}
    ['chrome', 'runtime', 'browser', '__nightmare', '__webdriver_script_fn'].forEach(k => {
      try { delete window[k]; } catch (e) {}
    });"""

# navigator.platform patch: 默认不注入(Windows 上真实值就是 Win32, 覆盖反而暴露),
# 仅在 render_stealth_script(patch_platform=True) 时启用。
_PLATFORM_PATCH_JS: str = """
    Object.defineProperty(navigator, 'platform', {
      get: () => 'Win32', configurable: true, enumerable: true,
    });"""

# navigator.userAgent patch: 默认不注入(launch 时 user_agent 已设为对应 UA,
# 覆盖会与真实 UA 不一致),仅在 render_stealth_script(patch_ua=True) 时启用。
_UA_PATCH_JS: str = """
    Object.defineProperty(navigator, 'userAgent', {
      get: () => '%UA%', configurable: true, enumerable: true,
    });"""

# Canvas 指纹微噪: 默认不注入(固定微噪反而引入固定差异, 同会话稳定可能触发一致性检测),
# 仅在 render_stealth_script(patch_canvas=True) 时启用。
_CANVAS_PATCH_JS: str = """
    try {
      const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
      const origGetImgData = CanvasRenderingContext2D.prototype.getImageData;
      HTMLCanvasElement.prototype.toDataURL = function(t, q) {
        const s = (q === undefined || q > 1) ? 1 : q;
        const c = this.getContext('2d');
        if (c) {
          const d = c.getImageData(0, 0, this.width, this.height);
          const px = d.data;
          for (let i = 0; i < px.length; i += 4) {
            px[i] = (px[i] + (i % 7)) & 255;
            px[i + 1] = (px[i + 1] + (i % 5)) & 255;
          }
          c.putImageData(d, 0, 0);
        }
        return origToDataURL.call(this, t, s);
      };
      CanvasRenderingContext2D.prototype.getImageData = function(sx, sy, sw, sh) {
        const d = origGetImgData.call(this, sx, sy, sw, sh);
        const px = d.data;
        for (let i = 0; i < px.length; i += 4) {
          px[i] = (px[i] + (i % 7)) & 255;
          px[i + 1] = (px[i + 1] + (i % 5)) & 255;
        }
        return d;
      };
    } catch (e) {}"""


def _chrome_major(ua: str) -> str:
    """从 UA 提取 Chrome 主版本(如 'Chrome/120.0.0.0' → '120')。"""
    import re
    m = re.search(r"Chrome/(\d+)", ua)
    return m.group(1) if m else "120"


def render_stealth_script(profile: dict | None = None, ua: str | None = None,
                          clean_cdp: bool = False,
                          patch_platform: bool = False,
                          patch_ua: bool = False,
                          patch_canvas: bool = False) -> str:
    """用指定浏览器指纹渲染反检测脚本。

    参数:
      profile: get_profile() 返回的字典
      ua: 指定 UA 字符串(优先级高于 profile)
      clean_cdp: 是否清理 CDP/playwright 泄露变量(默认 False)
      patch_platform: 是否覆盖 navigator.platform=Win32(默认 False)
      patch_ua: 是否覆盖 navigator.userAgent(默认 False)
      patch_canvas: 是否注入 Canvas 指纹微噪(默认 False)
    默认用 UA 常量(= BROWSER_PROFILES[0])渲染,保持向后兼容。
    默认均不启用覆盖型 patch(platform/userAgent/canvas),避免与真实环境不一致暴露。
    """
    cdp_cleanup = _CDP_CLEANUP_JS if clean_cdp else ""
    platform_js = _PLATFORM_PATCH_JS if patch_platform else ""
    ua_js = _UA_PATCH_JS if patch_ua else ""
    canvas_js = _CANVAS_PATCH_JS if patch_canvas else ""
    if ua is None:
        p = profile if profile is not None else BROWSER_PROFILES[0]
        ua = p["ua"]
        p.setdefault("gpu_vendor", "Intel Inc.")
        p.setdefault("gpu_renderer", "Intel GPU")
        p.setdefault("cores", 8)
        p.setdefault("mem", 8)
        out = _STEALTH_TEMPLATE
        out = out.replace("%UA%", ua)
        out = out.replace("%CHROME_MAJOR%", _chrome_major(ua))
        out = out.replace("%CORES%", str(p["cores"]))
        out = out.replace("%MEM%", str(p["mem"]))
        out = out.replace("%GPU_VENDOR%", p["gpu_vendor"])
        out = out.replace("%GPU_RENDERER%", p["gpu_renderer"])
        out = out.replace("%CDP_CLEANUP%", cdp_cleanup)
        out = out.replace("%PLATFORM_PATCH%", platform_js)
        out = out.replace("%UA_PATCH%", ua_js)
        out = out.replace("%CANVAS_PATCH%", canvas_js)
        # _UA_PATCH_JS 内含 %UA%,在插入后再替换一次
        out = out.replace("%UA%", ua)
        return out
    # 仅指定 UA,硬件用默认
    out = _STEALTH_TEMPLATE.replace("%UA%", ua).replace("%CHROME_MAJOR%", _chrome_major(ua))
    out = out.replace("%CORES%", "8").replace("%MEM%", "8")
    out = out.replace("%GPU_VENDOR%", "Intel Inc.").replace("%GPU_RENDERER%", "Intel GPU")
    out = out.replace("%CDP_CLEANUP%", cdp_cleanup)
    out = out.replace("%PLATFORM_PATCH%", platform_js)
    out = out.replace("%UA_PATCH%", ua_js)
    out = out.replace("%CANVAS_PATCH%", canvas_js)
    out = out.replace("%UA%", ua)
    return out


# 向后兼容: 默认渲染的完整脚本
STEALTH_SCRIPT: str = render_stealth_script()