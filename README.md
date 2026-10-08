# 中国官方电视直播 · 英国 APTV 检查项目

**当前没有已验证可播放的频道。** 首次英国本机检查覆盖 33 个频道（CCTV-1 至 CCTV-17、5+、4 欧洲/美洲，以及 13 个主要卫视）。因此 M3U 只有文件头，导入 APTV 后不会出现频道。这是实际检查结果，不是已实现全频道播放的承诺。

本项目维护频道元数据、官方来源证据、网络检测和 M3U 生成。没有破解、直播转发、抓取第三方 IPTV 列表或虚构链接。

## 固定订阅与报告

- 英国验证订阅：[uk.m3u](https://raw.githubusercontent.com/Gasiro/china-tv-official/main/public/uk.m3u)
- [英国逐频道报告](reports/uk.md) · [结构化证据](reports/uk.json)
- [订阅状态与有效期](public/uk-status.json)
- GitHub Actions 部署后提供 [云端报告](reports/cloud.md)，云端结果不等于英国可播放。

当 `uk.m3u` 出现经过验证的条目后，在 APTV 的配置/订阅导入处添加上述 URL，并启用定期刷新。菜单名称可能随版本不同。当前空列表不必反复排查 APTV 设置。未在用户 APTV 中执行人工播放测试。

## 检查结论与边界

- 央视：官方 PC 配置明示 `encrypted: true`。停止在配置层，不尝试解密；不能据此断言每个 CCTV 频道的视频均使用 DRM，也不能断言其英国网页一定不可播放。
- 河南、山东：静态播放器代码存在签名或加密配置逻辑，未生成签名、未解密响应。
- 湖北：官方页面中频道对应的 HLS 含时效签名。本项目不将带签名链接复制到公开订阅，也不删掉签名试探。
- 江苏：初次直接请求官方 HLS 返回 403；批量检测也可能超时。403 原因未确定，不能归因为英国地域限制。
- 其他频道：可能使用动态接口，或遇到超时、证书、访问限制，保留为未验证。

“受限”包括本项目在鉴权/加密处停止，不意味着已经证实该频道付费、DRM 或地域封锁。“未验证”不等于不可播放。成功读取网页不等于成功读取媒体。

公开官网链接和技术可访问性不构成电视台授予第三方再分发的许可；本项目只提供个人技术核查及官方链接，不托管视频。未作“所有地址都获得明确第三方播放授权”的法律判断。

## 本机运行

需要 Python 3.10+、curl、ffmpeg（含 ffprobe）。本机已具备这些工具。项目仅使用 Python 标准库。

```sh
python3 -m unittest -v
python3 maintain.py --scope uk
```

脚本用 Cloudflare 的国家代码确认出口，只保存 `GB` 等国家代码，不保存 IP。若未确认为英国，英国订阅会清空并标注原因，不允许通过命令行伪造英国地区。

通过标准：唯一且明确对应频道的官网地址、HTTPS、无凭据/查询参数、清单无加密声明、两段 MPEG-TS 可读取并解码出音视频、直播清单继续推进。本版本不验证 fMP4、字节范围和分离音轨，保守保留为未验证。对标准 AES-128 也不取密钥；这是项目的支持范围，不是把所有 AES HLS 都认定为 DRM。

只有当次通过且出口 GB 的频道进入 `public/uk.m3u`，不会将上次的失效地址混进来。`tvg-id` 是稳定内部标识；尚未接入有授权来源的 EPG 或图标，不提供虚假节目单。

## GitHub 部署

本仓库已部署到 [Gasiro/china-tv-official](https://github.com/Gasiro/china-tv-official)。下面的创建命令仅供重新部署参考；若已有仓库，不要重复创建。若部署到其他仓库，请替换文档中的账号和仓库名。

```sh
gh auth status
# 只有上传工作流时提示缺少权限，才执行：
gh auth refresh -h github.com -s workflow

git init -b main
git add .
git commit -m 'Add official-source TV audit and M3U generator'
gh repo create Gasiro/china-tv-official --public --source=. --remote=origin --push
```

已存在的仓库无需再次创建。在 GitHub 的 Actions 页面启动 `Check official TV sources`。工作流每 6 小时（UTC 00:23、06:23、12:23、18:23）检测一次，提交云端报告，并清理过期英国条目。GitHub 定时任务可能延迟；公开仓库长时间无活动可能自动停用定时任务，应定期检查 Actions。

官方说明：[定时工作流](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。工作流需要仓库 contents 写入权限；组织策略可覆盖工作流权限。

**默认 GitHub 托管机器不保证位于英国。** 它们只更新云端报告，不为 `uk.m3u` 增加频道。英国结果 24 小时后失效，云端下一次成功运行时清空订阅（若 Actions 停运，静态 URL 无法主动过期，请检查状态文件）。

要长期产生英国验证结果，可在英国 Mac 上定期运行以下命令，或按下一节启用专用英国自托管 runner：

```sh
git pull --ff-only
python3 maintain.py --scope uk
git add public/uk.m3u public/uk-status.json reports/uk.json reports/uk.md
git diff --cached --quiet || git commit -m 'Refresh UK validation'
git push
```

建议英国验证频率为每 6 小时。Mac 休眠、断网时不能检测；订阅状态中的有效期始终可查。没有安装后台常驻任务或改变系统网络设置。

## 可选英国自托管 Actions

已附带 `uk-check.yml`，默认不运行。需在英国专用机器按 GitHub 仓库 Settings → Actions → Runners 的官方指引注册 runner，增加标签 `uk-tv`，安装上述依赖，再设置仓库变量 `UK_TV_RUNNER_ENABLED=true`。两个工作流共用并发锁，避免相互覆盖提交。

该工作流仅允许定时和手动运行，不响应 PR，不把 `GB` 当作配置项。注册 runner 涉及持久化账户权限，未替用户安装或注册。官方说明：[添加自托管 runner](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners)。

## 如何维护新频道

1. 先核对电视台官网及频道身份，在 `channels.json` 记录入口、允许域名和证据位置。
2. `manual` 频道只检查入口，不能自动收录；需要实际核查后添加针对该频道的解析规则。
3. `literal` 用明确频道对应的规则提取单一地址；页面没有匹配或匹配多个都停下，不猜 URL。
4. `guard` 只监测已发现的鉴权证据；证据变化会提示人工复核，不自动尝试绕过。
5. 官网带版本号的脚本更新时，需要复核并更新 `evidence_url`。此项目不承诺能自动适应所有网站改版。
6. 运行测试和英国检测，确认报告与媒体一致后再发布。

排错时保持 TLS 校验；遇到 401/403/451，不伪造地域、Referer、Cookie 或签名。不要将网页登录态、临时 token、带签名地址和原始响应提交到公开仓库。
