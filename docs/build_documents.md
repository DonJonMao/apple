# 重建中文使用手册

安装 `reportlab` 后，提供允许嵌入的中文 TrueType 字体。工具不会联网下载字体，也不再使用依赖阅读器替代字体的未嵌入CID字体。

```bash
python -m pip install reportlab
HEALTHZIP_MANUAL_FONT=/path/to/ChineseFont.ttf python tools/build_user_manual_pdf.py
```

默认查找 `.local/fonts/NotoSansSC.ttf`。本次使用 Noto Sans CJK SC 的中文子集，保留其许可证信息并转换为 TrueType 轮廓后嵌入PDF；字体和构建缓存不进入私人健康库。Noto字体采用SIL Open Font License，可从Google Fonts的官方仓库取得，使用时遵守字体许可。

产物为 `output/pdf/HealthZIP_使用手册.pdf`。构建后检查中文可提取且实际渲染可见，不能只以文件存在作为验收。当前结果和文件哈希见 `artifacts/verification/manual-pdf.json`。
