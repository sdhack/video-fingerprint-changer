<div align="center">

# 🎬 视频指纹修改器

**批量修改视频文件 MD5 指纹 · 文件大小不变 · 画质零损失 · 拖入即用**

让广告投放平台(如千川后台)把同一个素材识别为**全新视频**

[![Windows](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows11&logoColor=white)](https://github.com/sdhack/video-fingerprint-changer/releases)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Release](https://img.shields.io/badge/Release-v1.1-blue)](../../releases)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

免安装 · 免费开源 · Windows 10/11

</div>

---

## ✨ 功能特性

| 特性 | 说明 |
|------|------|
| 🔒 **大小不变** | 随机数据等长写入视频空闲区,文件一个字节都不变大 |
| 🖼️ **画质零损失** | 不重新编码,音视频数据(mdat)完全不动 |
| ⚡ **极速处理** | 单遍流式拷贝 + 边拷边注入,实测可达 **200+ MB/s** |
| 🚀 **秒开启动** | 目录式免解压打包,冷启动 <1s、热启动 ~0.4s,逼近原生体验 |
| 🖱️ **拖入即用** | 视频/整个文件夹直接拖进窗口,自动递归扫描 |
| 📦 **批量多副本** | 一个视频一键生成 N 份不同指纹的副本,多线程并发 |
| 🏷️ **CRC 命名** | 输出文件自动带上自身 6 位 CRC 校验码,天然不重名 |
| 📋 **完整日志** | 每个文件的成功/失败均落盘记录,失败附带原因 |
| 🧰 **兜底模式** | 极少数无空闲区的文件可选择尾部附加,保证出结果 |

## 🚀 快速开始

1. 从 [Releases](../../releases) 下载 `视频指纹修改器_v1.1.zip`,解压到任意位置
2. 双击文件夹内的 `视频指纹修改器.exe`(免安装,秒开)
3. 把视频文件或文件夹**拖进窗口**
4. 设置输出目录与份数,点击 **开始处理 ▶**,完成后一键打开输出目录

> 📝 版本变更记录见 [CHANGELOG.md](CHANGELOG.md)

```
产品视频A.mp4  ──►  产品视频A_F40D51.mp4   (大小相同,MD5 全新)
```

## 🔬 工作原理

MP4/MOV 文件由一系列 box(原子)组成,其中 `free`/`skip` 是预留的空白区,
很多导出工具还会在文件末尾留一大段纯零填充。本工具把一段随机字符串**等长替换**
写入这些区域:

```
┌──────┬─────────┬──────────────┬────────┬─────────────┐
│ ftyp │  free   │     mdat     │  moov  │  尾部零填充  │
└──────┴────▲────┴──────────────┴────────┴──────▲──────┘
            │                                    │
       随机串等长写入,大小不变,mdat 完全不动
```

- ✅ 文件大小不变
- ✅ 画质、时长、可播放性不受影响
- ✅ 整文件 MD5/SHA1/CRC32 全部改变 → 平台判重指纹通过
- ✅ 无需转码,速度等于纯磁盘拷贝

### 空白区识别策略(按优先级)

1. `free` / `skip` 空闲原子(标准 MP4 空白区)
2. 文件末尾"延伸到文件尾"的全零填充 box(验证内容后利用)
3. 若均不存在 → 兜底模式:尾部附加随机串(24~128 字节,可关闭)

## 🖥️ 界面预览

- **添加区**:拖拽 / 添加文件 / 添加文件夹 / 清空,实时统计数量
- **输出设置**:输出目录、每个视频生成份数(1~100)、并发线程数、兜底开关
- **运行日志**:带时间戳,同步写入输出目录下的 `处理日志.txt`

## ⌨️ 命令行调用(可选)

```python
from fingerprint import make_fingerprint, fingerprint_inplace, file_hash

# 生成指纹全新的副本:大小不变,返回输出文件的 6 位 CRC
crc6 = make_fingerprint("源视频.mp4", "输出.mp4")            # -> "F40D51"

# 无空白区时允许尾部附加(文件最多增大 128 字节)
make_fingerprint("源视频.mp4", "输出.mp4", allow_append=True)

# 原地修改(不生成副本,大小不变)
fingerprint_inplace("视频.mp4")

# 校验
print(file_hash("输出.mp4"))                                  # md5
```

## 🛠️ 从源码运行 / 打包

```bash
pip install tkinterdnd2
python 视频指纹修改器.pyw            # 直接运行

pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed \
    --name "视频指纹修改器" --collect-all tkinterdnd2 \
    --exclude-module unittest --exclude-module pydoc --exclude-module doctest \
    --exclude-module test --exclude-module xmlrpc --exclude-module pygments \
    "视频指纹修改器.pyw"             # 打包(onedir 免解压,启动快)
```

> 💡 为什么不用单文件 exe?onefile 每次启动都要把运行时解压到临时目录(2~4 秒),
> onedir 目录式打包免解压,冷启动 <1 秒,更接近原生应用。

## ❓ 常见问题

**Q: 为什么有的文件提示"未找到 free/skip 空闲原子"?**
个别相机直出或经过特殊处理的 MP4 没有任何空白区。保持"兜底模式"勾选即可正常输出(文件会增大不超过 128 字节),或用剪辑软件重新导出一次。

**Q: 修改后的视频能正常播放吗?**
能。改动只发生在预留空白区,播放器解析时直接跳过这些区域。

**Q: 支持哪些格式?**
MP4 / MOV / M4V 等 box 结构容器均可;其他格式请先转换。

**Q: 杀毒软件报毒?**
PyInstaller 打包的程序偶尔被误报,将整个程序文件夹添加到杀软信任区即可。

**Q: 跨电脑能用吗?**
能。exe 已内置全部运行环境,拷贝到任意 Windows 10/11 64 位电脑直接运行。

## 📁 项目结构

```
├── 视频指纹修改器.pyw    # GUI 主程序
├── fingerprint.py        # 指纹修改核心模块(可独立调用)
├── build.bat             # 一键打包脚本
├── CHANGELOG.md          # 版本更新日志
└── README.md

程序成品(免解压 zip)请到 Releases 页面下载,不进入版本库。
```

## ⚠️ 免责声明

本工具仅用于**自有素材**的广告投放去重等合法场景,请遵守所在平台的服务条款与相关法律法规,由此产生的任何问题与开发者无关。

## 📄 License

[MIT](LICENSE)
