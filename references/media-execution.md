# 媒体执行

## 建议产物目录

```text
<run-directory>/
  source-manifest.json
  transcripts/
  opening-candidates.json
  selected-openings.json
  report.md
  <opening-id>/                 # 三个已选开头各一份
    selected-opening.json
    edit-plan.json
    continuous-v1.m4v
    cold-open-v1.m4v            # 仅可行时生成
    boundary-review/
      boundary-refinement.json
    review.md
```

源素材、中间件和粗剪保存在本地运行目录；ASR 阶段通过 MediaKit CLI 把指定视频交给 MediaKit Cloud 处理，其余阶段不上传素材。

## 工具链

默认使用 Skill 内置的 `bin/macos-arm64/ffmpeg` 与 `ffprobe`（9.0.2），无需项目工具或系统安装。启动器按自身位置解析目录，不写死个人路径。仅支持 macOS arm64；平台不符、文件缺失或无法运行时明确报错，不静默回退。用户显式指定外部工具时才绕过启动器，验证同版本且 FFmpeg >= 5.1、支持 `libx264`，并直接设置绝对路径。一次运行期间不得混用两套版本。

默认调用方式（`<skill-root>` 为当前 Skill 的实际目录）：

```bash
sh <skill-root>/scripts/with_ffmpeg.sh ffmpeg -version
sh <skill-root>/scripts/with_ffmpeg.sh ffprobe -version
sh <skill-root>/scripts/with_ffmpeg.sh <compiled-wrapper> <input-video> <output-video> <options>
```

不带参数执行启动器会打印两个绝对路径，用于登记 `source-manifest.json`。复制整个 Skill 目录会同时带走二进制；平台、版本、校验值及来源见 [随包工具说明](../bin/macos-arm64/NOTICE.md)。

所有探测和裁剪命令直接调用已记录的绝对路径。启动每个 Swift 包装程序时传入 `FFMPEG_PATH="/absolute/path/to/ffmpeg"`；脚本会在渲染前检查该路径并直接执行它，缺失或不可执行时失败，不回退 PATH。`FFPROBE_PATH` 用于执行者调用探测与验收，不是 Swift 包装程序的依赖。以上路径仅为运行配置，不应把本机路径写进 Skill。

1. 基础媒体处理默认使用随包 FFmpeg/FFprobe；标题、冷开转场和片尾冻结使用随 Skill 提供的 Swift/AVFoundation 包装脚本。完整渲染仍要求 macOS 和 Xcode Command Line Tools；打包 FFmpeg 不代表消除了 Swift 或 ASR 依赖。
2. 在 `source-manifest.json` 记录 `ffmpeg_path`、`ffmpeg_version`、`ffprobe_path`、MediaKit CLI 路径和版本、ASR 模式、源文件大小、修改时间、SHA-256、时长、帧率、分辨率和音视频编码。
3. 媒体探测、音轨提取、定点抽帧、联系表、剧情裁剪、基础拼接、转码和技术验收由 FFmpeg/FFprobe 完成；Swift/AVFoundation 只处理标题、静帧、问题卡、倒放和片尾冻结。Codex 基于剧本、ASR 和抽取的真实帧做内容判断。
4. ASR 固定调用 MediaKit Cloud `video asr-subtitles`。调用前加载 `byted-mediakit-shared` 与 `byted-mediakit-video`，读取 `asr-subtitles` 和 `query-task` reference，并以当前 CLI 的 `--help`、`--schema` 为机器合同。每次真实命令都设置 `MEDIAKIT_SURFACE=skill` 和 `MEDIAKIT_RUNTIME=codex`。
5. FFmpeg 和 Swift 包装脚本都不是 ASR 或视频语义模型。不得将音轨提取、镜头变化检测或运动量计算记录为已完成语音识别或内容理解。
6. 开始完整渲染前必须同时验证 `ffmpeg`、`ffprobe` 和 `xcrun swiftc`；缺少任一项时只完成仍可验证的上游阶段，并在报告中列出受阻步骤。

## 时间索引

1. 登记所有允许使用的视频路径、集数、素材指纹和 FFprobe 真实时长。
2. 查找已有逐句时间码；只有在素材指纹、识别语言和 MediaKit 来源记录匹配时才复用。其他引擎、缺少来源记录或指纹不一致的转写不得复用。
3. 需要新建 ASR 时，向 MediaKit Cloud `video asr-subtitles` 传递真实本地视频路径；由 CLI 完成输入适配，不自行添加协议前缀。语言能由剧本和素材可靠确定时传 `--language`，普通对白可传 `--content-type speech`；为边界检查启用置信度，说话人区分确有帮助时再启用说话人信息。
4. 提交后保存真实 `task_id`，再用 `shared query-task --poll-complete` 等待终态。将原始提交结果、终态结果和规范化逐句结果都保存到本地 `transcripts/`，不得只保留整理后的文本。
5. 每份规范化转写保存逐句 `start_time`、`end_time`、`subtitle_text`，以及实际返回时的 `confidence`、`speaker`；同时记录源素材 SHA-256、MediaKit CLI 版本、Cloud 模式、识别语言、任务 ID、请求 ID 和结果时长。结果时长必须与 FFprobe 时长进行容差核对，明显不符时禁止使用。
6. MediaKit CLI 不可用、未鉴权、提交失败、查询失败或任务进入失败终态时，不改用本地 ASR 或旧项目转写；停在纯剧本计划，把真实时间码标记为未完成并保留真实错误。
7. 用剧本中的实际台词在 ASR 中定位，不只依赖摘要或场次标题。ASR 漏词时用相邻台词和真实视频校正，并把修正写入记录。

参考调用；实际参数必须以当前 MediaKit CLI 的机器合同为准：

```bash
MEDIAKIT_SURFACE=skill MEDIAKIT_RUNTIME=codex \
  mediakit-cli --cloud video asr-subtitles \
  --video-url <input-video> --content-type speech --enable-confidence=true

MEDIAKIT_SURFACE=skill MEDIAKIT_RUNTIME=codex \
  mediakit-cli shared query-task --task-id <task-id> --poll-complete
```

## 定点抽帧与视觉检查

- 不按固定间隔遍历整集。先用剧本和 ASR 确定开头锚点、边界近似时间和跨段连接，再用 FFmpeg 在局部时窗提取候选帧。
- 开头前 `4.0` 秒至少提取四帧；每个普通切口只在近似时间前后各 `1.0` 秒检查，技术片头片尾可扩展到前后各 `2.0` 秒。
- 需要判断动作与表情时，用相邻多帧联系表，不用单张截图代替连续性判断。
- Codex 必须实际查看抽取帧或微预览后才能将视觉证据标记为 `video_verified`。镜头变化、运动量和音量检测只负责提出候选。

指定时间点抽帧参考命令：

```bash
ffmpeg -ss <seconds> -i <input-video> -frames:v 1 -vsync 0 <output.png>
```

## 裁剪与拼接

固定渲染顺序为：计划校验 -> 裁剪并拼接剧情基线 -> 冷开版本插入静帧/问题卡/倒放 -> 压制头顶字幕 -> 添加末帧保持与静音或合格鼓点 -> 实际媒体验收。连续版跳过冷开转场步骤。每步使用独立输出，重试从该步上游输入开始，不在已包装文件上重复叠加。

Swift 脚本使用 `@main`，须用 `xcrun swiftc -parse-as-library <script.swift> -o <executable>` 编译。当前脚本负责包装渲染，不负责自动生成剪辑决策、视觉设计参数或切口候选；这些判断由执行者依据真实证据完成并留档。

渲染前用 FFprobe 逐源文件确认帧率和真实时间戳。Swift 包装脚本默认直接使用源视频轨的 `minFrameDuration`，保留 `24000/1001`、`30000/1001` 等非整数时间基准，不得四舍五入成整数 fps。可变帧率输入必须先用 FFmpeg 规范化为计划中记录的恒定帧率；无法取得有效帧时长时脚本必须失败，不得回退成 `1fps`。

三个包装脚本先用 AVFoundation 完成视觉包装，再调用本地 FFmpeg 按源轨有理数帧率执行最终 CFR 规范化；FFprobe 验收的 `r_frame_rate` 和 `avg_frame_rate` 必须与源轨一致。最终文件必须先导出到目标目录中的 UUID 临时文件，全部步骤成功后再原子替换正式输出。任一步失败时保留上一份有效输出，并清理本次临时文件；不得在导出开始前删除正式文件。

- 裁剪前读取 [boundary-refinement.md](boundary-refinement.md)，先锁定每个开始点、结束点及非连续连接的具体源帧，并保存 `boundary-review/boundary-refinement.json`。普通切口默认只搜索近似时间前后各 `1.0` 秒，技术片头片尾前后各 `2.0` 秒；只有信号冲突或置信度不足时才生成微预览。
- 先按计划裁剪独立源区间，再按 `ranges` 顺序拼接。
- 若相邻区间来自同一视频且前一段 `end` 等于后一段 `start`，渲染前合并为一个裁剪区间，避免为了结构标签制造无意义切口。
- 默认使用硬切，不用转场效果掩盖错误边界。
- 锁定两版全部剧情区间后，才从开头前 `4.0` 秒抽取至少四个代表帧，自动生成唯一一组三行英文头顶字幕并选择基础色与强调色。字幕只能补必要信息或承担强留存钩子，不得反向改变已经锁定的开头、冷开回接版第二段、恢复点和尾钩。先在代表帧上检查顶部区域可读性、人物遮挡和原片文字冲突；失败时自动换色、重新断句或缩小字号，不等待人工确认。
- 两版完成剧情拼接后，编译 `scripts/overlay_opening_headline.swift`，使用 `--hold-duration 3.0`、`--fade-duration 1.0`、三行 `--line1/2/3` 文案，以及计划中记录的 `--base-color '#RRGGBB'`、`--accent-color '#RRGGBB'` 压制标题。标题顶部居中、无矩形底框，不能遮挡人物或原片字幕；输出 `.m4v` 以使用 Apple 兼容编码预设。
- 冷开回接版必须在 `opening_window` 后、`reset_context` 前依次插入 `0.8` 秒静态末帧、`2.0` 秒黑屏问题字幕卡和 `1.0` 秒完整前情快速倒放；三者都不是剧情源视频区间，不得加入 `ranges`。
- 字幕卡必须同时包含按输出帧率生成的 `2.0` 秒黑色视频与 `2.0` 秒真实静音音轨，两条轨道从同一时间点开始并同时结束。静帧同样静音；不得只生成视频层并依赖音轨隐式空洞。
- 先把未加转场的冷开回接版时间线按 `opening_window -> reset_context -> opening_echo -> resume_after_opening -> ending_hook` 拼好；`opening_echo` 只取冷开结尾最后一句或最后一个动作的完整源区间。再编译 `scripts/insert_rewind_transition.swift`，在 `opening_window` 结束点使用 `--pre-freeze-duration 0.8`、`--pre-card-duration 2.0`、`--pre-card-text '第一行|第二行'`、`--source-position after`、`--source-duration <reset_context 总时长>`、`--transition-duration 1.0`；输出 `.m4v` 以使用 Apple 兼容编码预设。完成回接转场后再压制开头剧情标题。
- 倒放必须覆盖完整 `reset_context`，原对白静音并使用短倒放音效；倒放末段减速落到该段第一帧，正常前情从第二帧恢复。不要从已经插入过字幕卡或倒放的文件再次执行脚本。
- 每条成片拼接完成后，用 `scripts/apply_punch_end.swift` 的 `--motion shake` 冻结最终帧 `1.0` 秒。震动只在开始时短促发生并衰减回原位置；不得缩放、渐变或持续抖动。
- 优先用 FFprobe 取得承载当前结尾的原剧集文件时长，并检查其最后 `1.0` 秒。只有计划确认该区间是鼓点或撞击尾音、不含对白或人声、且不与紧邻剧情尾部重叠时，才按原速、原音量直接使用；不得添加淡入淡出、增益、变速或替换声音内容。该区间不合格时检查其他原剧尾音，仍无合格音效则静音回退。
- 片尾段不加入 `ranges`，但计入输出文件实际时长。合格音效使用 `--audio-mode impact --sound-video ... --sound-start <source-duration-minus-1.0> --cut-time ... --effect-duration 1.0 --motion shake`；静音回退使用 `--audio-mode silence`，其余参数相同。输出 `.m4v` 时使用 Apple 兼容编码预设。
- 视频文件的集尾黑场、片头重复画面和编码填充应视为技术边界候选，不视为剧情内容。

## 边界抽查

至少检查：

- 两版第一秒。
- `boundary-refinement.json` 是否覆盖每个实际切口，记录的时间、帧号和源文件是否与最终裁剪一致。
- 开头剧情标题是否使用计划记录的自动配色，完整显示 `3.0` 秒并在第 `3.0-4.0` 秒平滑淡出；抽查四个代表帧，确认无矩形底框、文字可读且不遮挡人物或原片字幕。
- 开头结束与静帧、静帧与问题字幕卡、字幕卡与倒放、倒放与回接入口的四个连接。
- 静帧是否恰为 `0.8` 秒、画面完全不动且静音；问题字幕卡是否恰为 `2.0` 秒、黑底、静音，文案是否承接当前悬念且在手机画幅上清晰可读。
- 倒放是否恰为 `1.0` 秒、覆盖完整前情并准确落回第一帧；正常前情是否从第二帧恢复且没有重复停顿。
- 从第二段选定入口连续检查到追上开头：入口必须独立成立，计划记录的直接原因、人物动机和必要关系背景依次可见，追上前至少发生一次有效变化或升级。若任一项缺失，向前扩展一个自然叙事单元并重新渲染，不用固定秒数补救。
- 倒放后的首个可见说话动作与对应台词是否同步；不能只凭“字幕卡无声”和“文件含音轨”判断同步正常。
- 回接追上开头后，`opening_echo` 是否只完整重复最后一句或最后一个动作一次，以及它到新剧情恢复点的连接是否自然。
- 恢复后的停点是否位于开头爆点已经兑现之后，并形成第一个新的具体悬疑；开头原有问题尚未解决时不得提前结束。
- 每一个跨集连接。
- 两版最后一秒。
- 片尾是否恰好 `1.0` 秒，震动是否只在开始时短促发生、随后衰减回原位置，且没有放大或渐变。
- 鼓点或撞击音效是否来自计划区间，优先取当前结尾所在原剧集文件最后 `1.0` 秒；是否无对白或人声、不与紧邻剧情尾部重叠，并保持原速、原音量和完整内容。静音回退时是否明确记录原因。

在每个连接点前后抽取多帧联系表，检查人物、动作、物体和画面是否处于可理解状态。ASR 同时检查是否切断台词。

## 技术检查

确认每个实际生成的输出；冷开专属项在该版不适用时跳过：

- 可解码并包含视频轨。
- 音轨存在且未静音。
- 分辨率方向与源视频一致。
- 实际时长与计划区间总和基本一致。
- 冷开回接版实际时长包含 `0.8` 秒静帧、`2.0` 秒字幕卡和 `1.0` 秒倒放；两版实际时长都包含计划中记录的末帧冻结时长。
- 字幕卡的视频轨与静音音轨均实际存在，时长同为 `2.0` 秒；倒放后抽查至少一个清晰口型或动作声，确认音画没有整体偏移。
- 输出文件不是临时 URL 或空文件。
- 每个开头都记录自动生成的唯一标题、实际基础色与强调色，以及通过的代表帧可读性、人物遮挡和原片字幕冲突检查；流程未停在人工选稿或确认步骤。

工具或系统锁屏导致无法完整观看时，不得声称完成主观观看；仍可交付粗剪和边界抽查结果，并明确限制。
