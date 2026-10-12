# 热词、名称规范与整理稿格式

DeepSeek 整理稿附件不再输出 `[开始时间 - 结束时间]` 行，原稿仍保留时间戳；内部片段时间用于分块、缓存和恢复，不删除内部结构。用户上传文件的仅去时间戳副本保存在 `verification/terminology/律师如何低成本给Agent接上法律数据库_deepseek转写_无时间戳.md`，其余正文未改，原附件保持不变。

用户提供的 hotwords.txt 已纳入独立项目 `config/hotwords.txt`。注释忽略，每行一个条目，多词英文名称按同一个条目保留；HOTWORDS 环境变量仍可补充热词。默认 69 个去重词，新增 WorkBuddy、MCP、得理等场景词。未修改原 Video2Text1 的热词、模型或配置。

实际安装的 FunASR 1.2.7 / SeACo Paraformer 已只读核对：支持本地 .txt 热词路径。推理前将解析后的热词写到本任务 `asr-hotwords.txt`，传给 model.generate(hotword=路径)，避免把 Claude Code、TRAE Work 拆成两条独立提示。英文词仍受模型词表和发音能力限制，不能保证正确。

默认 `config/terms.txt` 是 DeepSeek 专有名词拼写参考，`config/term-aliases.json` 是 WorkBuddy 在该样本中出现的误识对照。整理指令要求根据语境规范名称、保持英文拼写，不猜造事实、不追加词表内容；不是对原稿做正则替换。混合语言特别多时，也可在提交前手动切到 Faster-Whisper 对比另一任务，不会自动同时运行两套引擎。

修改 config 文件后，下次任务读取新配置。基础 Compose 以只读方式将 config 挂入 manager/GPU，镜像也包含默认副本；单独运行镜像需重建或显式挂载配置。可通过 HOTWORDS_FILE、DEEPSEEK_TERMS_FILE、DEEPSEEK_TERM_ALIASES_FILE 指定其他本地文件。每个热词或名称一个条目，优先保留相关词，避免无限扩大词表。

热词内容纳入转写缓存键，术语及误识对照内容纳入整理缓存键；改词表后旧结果不能直接充当新结果。热词属于解码参数，不属于模型权重版本，校验模型配置时排除 hotwords，但仍核对模型 ID/revision/device/precision 和权重内容哈希，不需因热词变化重新下载模型。

本轮验证见 `verification/terminology/REPORT.md`。新生成的整理稿仍需人工核对；热词提高部分名称准确性，不代表全部识别错误已解决。
