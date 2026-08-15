"""跨技能共享的浏览器反检测常量与注入脚本(带类型注解)。

公拍网(gpai)与阿里资产(ali)爬虫共用的 User-Agent、启动参数与反检测注入 JS。
"""
from __future__ import annotations

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 反自动化识别: 关闭 automation 特性并去掉 playwright 默认识别的 --enable-automation
LAUNCH_ARGS: list[str] = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
]

# 反检测注入脚本(L1-L4): 页面加载前注入,patch 所有已知 CDP 泄漏点。
# 注意: 必须用 IIFE 立即执行,`add_init_script` 不会调用裸 `() => {}` 函数表达式。
# 使用阿里资产实测的增强版本(mimeTypes/maxTouchPoints/userAgentData 一并 patch)。
STEALTH_SCRIPT: str = """
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
    Object.defineProperty(navigator, 'hardwareConcurrency', {
      get: () => 8, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'deviceMemory', {
      get: () => 8, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'maxTouchPoints', {
      get: () => 0, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'vendor', {
      get: () => 'Google Inc.', configurable: true, enumerable: true,
    });
    const uaData = {
      brands: [
        { brand: 'Chromium', version: '120' },
        { brand: 'Google Chrome', version: '120' },
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
  } catch (e) {}
})();
"""