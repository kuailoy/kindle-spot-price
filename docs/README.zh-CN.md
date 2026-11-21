# kindle-spot-price 中文说明

在越狱的 Kindle Paperwhite 3 锁屏上显示芬兰当天的现货电价，原生阅读器照常使用。

<p align="center"><img src="preview-morning.png" width="300" alt="锁屏预览（示例数据）"></p>

## 图上有什么

图片上的文字是英文（High / Low / Best laundry 等），下面是各部分的含义。


- **今天 24 小时的电价柱状图**：每小时取 4 个 15 分钟价格的平均值，单位 c/kWh，含增值税
- **按价格分灰阶**：每 4c 一级，白色（< 4）到黑色（≥ 40）；虚线标出 8c（便宜）和 20c（贵）
- **当前小时**：柱子下方的三角形；右上角也写着这张图对应的小时，一眼能看出锁屏是不是旧的
- **最高价、最低价**的时段
- **最佳洗衣时段**：今天剩余时间里、7 点到 22 点之间最便宜的连续 2 小时；晚上已经没有合适时段时，改为显示明天的（明天的电价约 14 点公布）

价格是 Nord Pool 芬兰区现货价，含税，不含电力公司的加价和电网传输费。

## 原理

电价提前一天就确定了，所以图片可以全部预先画好。

1. **云端**：GitHub Actions 每小时运行一次，从 spot-hinta.fi 拉取电价，为今天和明天（约 14 点公布后）的**每个小时各画一张图**，发布到 GitHub Pages。不需要自己的服务器。
2. **Kindle**：脚本把内部存储里的一个文件夹"挂载"到系统锁屏图文件夹上，系统分区不做任何修改，重启后自动恢复原样。后台脚本只在 Kindle 醒着时运行：
   - Wi-Fi 开着、并且本地缺图时，下载一批图（一般一天一次，比如你晚上看书时）
   - 每到整点，以及每次唤醒 Kindle 时，换上当前小时的图，这一步不需要联网

详细技术说明见 [how-it-works.md](how-it-works.md)（英文）。

## 安装

### 第一步：发布图片

1. 把这个仓库推送到 GitHub
2. 仓库 **Settings → Pages**，**Source** 选 **GitHub Actions**
3. **Actions → Update price image → Run workflow**，手动运行一次
4. 约一分钟后，网址是 `https://<你的用户名>.github.io/kindle-spot-price/`（当前图片 `kindle.png`，每小时的图在 `frames/` 里）

### 第二步：Kindle

前提：Kindle 已越狱；锁屏设置为固定图片，不要选"显示封面"。

1. USB 连接 Kindle
2. 把 `kindle/ss_on.sh` 和 `kindle/ss_off.sh` 拷进 `documents` 文件夹
3. 在 Kindle 根目录建 `sslive` 文件夹，放入：
   - `url.txt`：只写一行网址，比如 `https://<你的用户名>.github.io/kindle-spot-price/`
   - `current.png`（可选）：任意一张 1072×1448 的灰度 PNG，只在还没下载到任何图时使用
4. 弹出 Kindle，打开 Wi-Fi，在书库里点 **Lockscreen ON**

- 点 **Lockscreen OFF** 或重启，恢复原来的锁屏，后台脚本也会停止
- 重启后需要再点一次 **Lockscreen ON**
- 运行日志在 `sslive/log.txt`

`kindle/ss_diag.sh` 是只读的检查脚本，会列出锁屏图片、可用工具和屏幕参数，换其他型号的 Kindle 时可以先跑一下。

## 目前的限制

- Kindle 锁屏后会深度休眠，后台脚本也会暂停，所以锁屏显示的是**锁屏那个小时**的图，右上角的小时能看出是哪一张。
- 下一步计划：锁屏期间每小时自动醒几秒，用本地已有的图刷新屏幕，再睡回去，不需要开 Wi-Fi。

## 注意

- GitHub 的仓库如果 60 天没有任何活动，定时任务会被暂停，GitHub 会发邮件通知，到 Actions 页面重新启用即可。
- 越狱有风险，后果自负。本项目的锁屏方法不写入系统分区，但不做任何保证。
