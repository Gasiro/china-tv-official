# 本次核查记录 · 2026-10-08

检测来自用户 Mac，出口国家代码 `GB`，Cloudflare WARP 状态 `off`。国家代码是出口识别，不能证明没有任何其他代理，也不能代表全英国所有运营商。脚本不改变代理、IPv6、DNS 或路由。

英国批量检查开始时间：03:40 英国夏令时（02:40 UTC）。完整机器报告记录逐项来源 URL、最终 URL、HTTP 状态与响应 SHA-256；未提交原始播放器脚本、访问 token 或响应正文。

| 对象 | 官方证据 | 本次观察 |
| --- | --- | --- |
| CCTV 频道清单 | [央视直播](https://tv.cctv.com/live/) | 覆盖 CCTV-1 至 17、5+、4 欧洲和美洲；9 和 14 的页面路径为 cctvjilu、cctvchild，未机械拼接错误路径 |
| CCTV 播放器 | [官网引用的 liveplayer.js](https://js.player.cntv.cn/creator/liveplayer.js) | 静态文本引用下述官方配置；未运行、解混淆或解密脚本 |
| CCTV PC 配置 | [version.json](https://api.live.cntv.cn/livestatic/zs/livestatic_config/pcweb/version.json) | 两份配置均明示 encrypted=true，未读取/解密其加密内容 |
| 江苏卫视 | [官方入口](https://live.jstv.com/) | 官方频道模块明确含频道对应 HLS；初次匿名直接 GET 返回 HTTP 403，之后批量检测超时；未加签名、Cookie、Referer 或替换主机名 |
| 山东卫视 | [官方直播](https://v.iqilu.com/live/sdtv/index.html) | 页面引用的 time-shifting-local.js 中，播放请求使用签名及加密配置，未调用 |
| 河南卫视 | [大象新闻电视直播](https://static.hntv.tv/kds/) | 频道请求使用 sign/timestamp，未生成或调用 |
| 湖北卫视 | [长江云电视直播](https://news.hbtv.com.cn/app/tv/431) | 页面包含对应 HLS，但有 auth_key；未删除、生成、复用或发布签名。不是媒体不可播放的实证 |
| 浙江卫视 | [Z视介直播](https://ztv.cztv.com/live/index.html) | 当前入口可访问；旧 tv.cztv.com 在本次网络无法解析。现有直播脚本带鉴权能力，但没有据此把频道判为 DRM |
| 东方卫视 | [看看新闻](https://live.kankanews.com/huikan?id=10) | 动态节目和播放数据，未确认可直接收录地址 |
| 东南卫视 | [官网直播入口](https://www.setv.fjtv.net/live/) | 本机 TLS 校验失败，未关闭证书校验 |

浏览器限制：内置浏览器安全策略拒绝打开央视播放页。未使用其他浏览器或脚本执行手段绕过；后续仅分析官方静态文本。因此没有网页画面验证或 APTV 人工播放验证。

技术检测的测试覆盖：主/子清单、相对 URL、HLS 加密标签、签名链接排除、HTML 假阳性、点播排除、域名边界、英国状态过滤、过期撤下、敏感查询参数脱敏，以及用本地产生的真实 H.264/AAC 样本验证解码和停滞清单检测。共 12 项测试通过。

下一步若要增加实际频道，需要找到官方明确可直接使用的未受限直播地址，或得到电视台支持第三方播放器的正式入口；目前没有依据宣称可用链接存在于已核查入口中。当前解析器有明确支持范围，未验证频道仍可能通过后续官方接口研究得到可用结果。
