# 结构化执行链路

本文件规定调度、证据交接和恢复方式，不替代选段、前情比较、边界、包装及验收规则。
完整新任务使用本链路；纯剧本任务仍按原约定交付 `script-plan.md`，不假造媒体阶段。
旧任务和旧成品不原地迁移、不自动补齐历史证据。续做旧项目可沿用原入口；需要使用新链路时另建运行目录。

## 职责分界

Codex 读取正文、比较开头和前情入口、查看真实帧、检查声音并生成方案。
程序只管理状态、证据、依赖、指纹、固定执行顺序和打包，不把字段存在或校验成功当作内容真实。
用户无需逐阶段确认；执行者按原 Skill 自动推进可验证的阶段。遇到真实工具故障、证据缺失或判断未通过时停在该阶段。

```text
intake -> index -> openings -> story -> boundaries -> packaging
                                                        |
                         每个实际版本: baseline -> [rewind] -> headline -> end
                                                        |
                                                    review -> package
```

每次命令入口为 `python3 <skill-root>/scripts/workflow.py <absolute-new-run-dir> <command>`。
`status` 返回下一阶段、现有状态、ASR 任务和交付记录，不启动云任务或渲染。

## 1. 初始化与冻结环境

新制作任务先按 [setup.md](setup.md) 完成只读环境检查并引导补齐缺失配置，再按 SKILL.md 的“运行选择”询问未明确的开头数量和冷开开关，等待回答；已明确或用户要求按默认时不重复问。确认后准备本次配置，使用 `init <config.json>` 初始化全新目录。API 密钥不写入该配置。CLI 的默认值用于兼容，不代表对话执行者可以跳过前置询问。
配置必须含实际路径和版本，不使用下方示意值作为真实数据：

```json
{
  "opening_count": 3,
  "cold_open_enabled": true,
  "language": "en",
  "scope": {"kind": "pre_paywall", "episodes": [1, 2, 3], "paywall": "实际收费点的正文锚点及视频范围"},
  "sources": [
    {"role": "script", "path": "/absolute/script.docx"},
    {"role": "video", "episode": 1, "path": "/absolute/EP1.mp4"},
    {"role": "suggestions", "path": "/absolute/suggestions.txt"}
  ],
  "tools": {
    "ffmpeg": {"path": "/absolute/ffmpeg", "version": "实际版本"},
    "ffprobe": {"path": "/absolute/ffprobe", "version": "实际版本"},
    "swiftc": {"path": "/absolute/swiftc", "version": "实际版本"},
    "mediakit": {"path": "/absolute/mediakit-cli", "version": "实际版本"}
  }
}
```

`opening_count` 为正整数，默认 3；`cold_open_enabled` 为布尔值，默认 `true`。也可在初始化时覆盖配置：

```sh
python3 scripts/workflow.py /absolute/new-run init /absolute/config.json --opening-count 1 --cold-open off
```

`--cold-open` 接受 `on` 或 `off`。init/status 均返回生效的两个选项。选 N 个开头，关闭冷开输出 N 条，开启时按可行性输出 N 至 2N 条；不是强制生成双版本。选项初始化后冻结，修改须另建运行，旧成品不变。

FFmpeg/FFprobe 仍默认选 Skill 随包工具；Swift 编译器可用 `xcrun --find swiftc` 定位。
程序计算素材、工具及 Skill 的 SHA-256 并保存到 `workflow.json`。素材建议的角色仅供参考，不是决策指令。
后续发现指纹变化会停止复用；不能把新源片或新 Skill 偷换进已有运行。工具不可用时保留纯剧本计划，不绕过依赖。

## 2. 阶段交接

`begin <stage>` 返回本次独立 `directory` 和所需检查项。所有本阶段文件写入该目录，引用路径相对此目录。
`finish <stage> receipt.json` 校验并冻结本阶段文件。未完成前置阶段不能进入下一阶段。
已完成阶段再次 `begin` 只返回已有记录，不重复生成。

每份 receipt 使用以下结构，检查项名称以 `begin` 返回的 `required_checks` 为准：

```json
{
  "artifacts": {"manifest": "source-manifest.json"},
  "checks": {
    "authorized_scope": {"status": "passed", "evidence": ["scope-review.md"]},
    "input_completeness": {"status": "passed", "evidence": ["source-probe.json", "scope-review.md"]}
  },
  "limitations": []
}
```

`passed` 必须来自实际完成的检查及相应记录，不能为了推进流程自动填写。
证据必须是阶段目录内的实际文件；禁止符号链接和跨目录引用。需要引用上游时保存本阶段引用说明或只读副本，不能修改已冻结产物。

| 阶段 | `artifacts` 内容 | 额外放行要求 |
| --- | --- | --- |
| intake | `manifest` 指向 source-manifest.json | `scope`、`sources` 与初始化后的 config 完全一致；保留实际探测和缺失项记录 |
| index | `index` 指向 transcripts/index.json | 覆盖所有已登记源片；任务、指纹、语言、Cloud 来源匹配 |
| openings | `candidates`、`selected` | 配置数量 N 个不同 ID；每项含 `candidate_id`、`event_anchor`、`source_video`、`episode`；记录完整正文比较和实际观众证据 |
| story | `plans` 为 opening ID 到草案 JSON 的映射 | N 个连续版；开启冷开时检查真实可行性、前情查全、入口比较、回声和新悬疑；禁止提前加入 `opening_headline` |
| boundaries | `plans`、`boundaries` 两份 ID 到文件的映射 | 不改变剧情语义，仅精修时间；边界记录与计划相符 |
| packaging | `plans`、`baselines` | 全部真实边界锁定后生成标题；运行原校验器；按锁定区间保存基线执行配方 |
| render | 可保存渲染总结 | 所有实际版本的固定渲染节点完成；不代表内容验收通过 |
| review | `review` 指向逐输出审阅 JSON | 每条文件分别通过技术检查和定点内容检查，披露连续观看限制 |

story、boundaries、packaging 的 `plans` 都以现有单开头计划结构为基础。将锁定的 `event_anchor` 同步放入 `selected_opening`；原校验器允许这一附加字段。
各计划顶层 `cold_open_enabled` 必须与运行配置一致，旧计划省略时按 `true` 处理。关闭时 `cold_open_eligibility` 只能包含 `status: not_evaluated`、`reason_code: disabled_by_user` 及非空 `reason`，不填写 `eligible` 或虚构的五项检查；`variants` 只有 `continuous`。
关闭冷开时 story 的 `required_checks` 仅为 `continuous_paths` 和 `cold_eligibility`，后者保存用户关闭的依据；不要求前情搜索、入口比较与回声检查。其他阶段的质量要求不变，渲染和声画复核按实际版本生成。
story 中先保存实际拟采用的源区间及叙事理由，不填造时间。没有完成 ASR/真实定位时不得提交完整阶段。
后续只允许在 boundaries 精修 `start`/`end`；剧情入口、路径顺序、前情比较、可行性和尾钩语义不能静默改变。

boundaries 的每个记录文件含 `locked_boundaries` 与 `evidence`：

```json
{
  "locked_boundaries": {
    "selected_opening": {"与该计划 selected_opening 完全一致": "此处仅示意"},
    "ranges": {"continuous": [], "cold_open": []}
  },
  "evidence": ["boundary-review/boundary-refinement.json", "boundary-review/contact-sheet.jpg"]
}
```

`ranges` 按实际版本填入完整源区间数组，不可使用空示意值；继续遵守语义合法区间、候选时窗、帧号和置信度规则。

## 3. ASR 的一次提交与恢复

在 index 阶段，提交前先执行 `task <source-sha256>`，仅首次返回 `submit_allowed: true`。
随后按 MediaKit Skill 的真实 CLI 发起一次提交，并立即用 `task <source-sha256> --task-id <actual-id>` 保存 ID。
重复执行只返回已有记录；已有任务应继续查询，不能再创建一个。
若停在 `submission_reserved` 且没有 ID，先查原提交日志与服务端结果；无法确定是否成功时报告阻塞，不盲目重传。
已确认的任务失败不自动重新提交，也不能改称剧情不适用；需要再次云端尝试时另行确认重试范围。

符合原 Skill 复用条件的已有 ASR，可登记来源一致的真实任务 ID 并复制原始、终态和规范化结果，无需重新上传。
`index.json` 的 `transcripts` 每项需含 `source_sha256`、`language`、`provider: mediakit-cloud`、`task_id`、`status: succeeded`，以及 `raw`、`terminal`、`normalized` 三个阶段内文件路径。
结果时长与源片时长的核对仍需真实探测证据，不能只凭任务成功。

## 4. 固定渲染与续跑

packaging 阶段为每个实际版本生成基线配方，`artifacts.baselines` 以 `<opening-id>.<variant-id>` 为键。
每份配方只含 `ranges`（与计划完全一致）、`video`、`audio`、`encoding` 四项。程序直接从锁定区间生成视频 trim、音频 atrim、时间戳归零及顺序拼接，不再接受独立手写的时间线命令。
旧 `argv` 配方会明确报错，不能自动沿用或仅改字段名绕过；根据本次已锁定计划生成新结构。旧视频不重渲染、不迁移。

```json
{
  "ranges": [{"source_video": "/absolute/EP1.mp4", "start": 10, "end": 20, "role": "opening_window"}],
  "video": {"width": 404, "height": 720, "fps": "30000/1001"},
  "audio": {"sample_rate": 48000, "channels": 2},
  "encoding": {"-c:v": "libx264", "-c:a": "aac", "-crf": "18", "-preset": "medium", "-pix_fmt": "yuv420p", "-b:a": "192k"}
}
```

上方仅示意字段，实际 `ranges` 必须完整复制锁定计划，尺寸、帧率和编码参数必须来自本次探测及已经核对的输出设置，不能把示例参数当全局默认值。
编码选项仅允许 codec、bitrate、CRF、preset、pixel format、movflags、threads、video track timescale，不允许用 `-ss/-t/-vf/-filter_complex/-map/-r` 改写时间线。
同源且时间连续的相邻区间按原规则合并，非相邻重复区间和倒序区间严格保留计划顺序，音视频使用同一组起止点。
实际执行前核对源时长、音轨、原始有理数帧率及画幅比例；帧率不符、区间越界或画幅被拉伸时停止，不静默改参数。复杂裁切、旋转和混合/VFR 规范化不属于这个编译器，需另行明确处理后登记素材。

`render` 顺序执行所有实际版本的节点。也可用 `execute <opening-id>.<variant-id>.<step>` 执行单节点；`wrap` 是同一执行入口的别名。

- baseline：运行冻结的 FFmpeg 配方，目标为新节点目录的 `output.m4v`，强制不覆盖。
- rewind：仅冷开版；直接调用原 Swift 实现及计划里的静帧、问题卡和完整前情倒放参数。
- headline：读取该节点上游输出，使用原文案、颜色和显示时间。
- end：读取标题节点输出，使用原片尾实现；计划静音就保持静音，不自行补鼓点。

每个节点保存命令、日志、输出指纹；失败立即停止。重试只创建新的节点目录并读取干净的上游文件。
已完成且依赖、参数、环境和输出指纹一致的节点直接复用。只改一个开头的标题时，其基线、冷开转场和其他开头的成片可复用，不重跑整套。
长任务中断留下 `running` 时，先确认进程是否仍运行；只有确认停止后才执行 `job-fail <job> <reason>`，再重试。
受管输出只能由 `execute/render` 成功执行后登记完成；旧 `job-finish` 命令会明确拒绝手动补录，防止拿任意视频绕过计划编译。`job-begin` 只保留用于状态诊断，不能用它配合旧脚本伪造受管节点完成。旧独立包装脚本仍可使用，但其输出不会自动进入本链路交付。

全部节点完成后保存 render receipt，再 `finish render receipt.json`。渲染成功不自动等同于交付。

## 5. 验收与交付

`begin review` 后运行 `inspect`，程序使用冻结的 FFprobe/FFmpeg 对实际输出进行全文件解码、音视频轨、全片非静音、时长、方向和有理数帧率检查，保存逐输出 JSON，并将报告指纹登记到本次阶段。手写成功报告、修改报告字段或引用旧阶段报告均不能放行。
混合帧率或 VFR 不自动转换；未满足已明确的恒定帧率要求时阻止交付，先在新方案中处理源片规范化。
检查只读媒体；音轨存在不代表口型同步，全片有声音不代表静帧和问题卡正确静音。

`inspect` 同时生成逐输出的内容复核 JSON 模板，绑定实际视频与当前计划的 SHA-256，自动列出第一秒、标题前四秒、冷开连接、完整前情段、回声与恢复、跨段连接和片尾的时间窗。所有窗口初始均为 `pending`，不能直接提交通过。
执行者必须实际连续播放这些窗口并听声音，填写 `reviewer`、每个窗口的 `observation` 和实际审阅记录/预览路径 `evidence`，完成后才设为 `passed`。截图或联系表可以辅助，但不能用 `mode: frames` 替代 `continuous_av`。无法观看或听取声音时保留未完成状态，不打包为已验收交付。
程序能校验窗口覆盖、记录完整和版本对应，不能证明填写者真实观看过，也不能自动判断剧情吸引力；禁止用脚本批量生成通过结论。
review JSON 的 `outputs` 以 `<opening-id>.<variant-id>.end` 为键，每项包含：

```json
{
  "sha256": "对应实际输出指纹",
  "technical": "passed",
  "targeted_content": "passed",
  "technical_evidence": "technical-实际目录/对应检查.json",
  "content_evidence": "technical-实际目录/对应输出-content.json",
  "continuous_viewing": "not_performed",
  "limitations": ["如实记录未连续观看及其他限制"]
}
```

`continuous_viewing` 描述整条成片是否完整连续观看，不能与关键窗口复核混淆。整片观看未完成可如实记录 `not_performed` 并披露限制，但所有关键窗口的连续声画复核仍是交付必要条件。
技术证据必须是本阶段程序生成的原始报告；内容证据必须绑定相同视频和当前计划，缺窗口、只看截图、复用旧计划结论或缺观察记录都不能放行。内容判断的真实性仍由实际复核者负责。
`finish review receipt.json` 通过后，`package` 只从已验收列表打包，生成独立 `deliveries/<id>/ads.zip` 与带指纹和限制说明的交付清单，不扫描目录凑视频数量。
交付后整次运行封存，重复打包返回原结果。后续版本另开运行，不改旧压缩包或视频。

## 6. 修改与失败

`fail <stage> <reason>` 记录真实失败；`revise <stage> <reason>` 显式撤销该阶段及下游的当前状态，历史记录和文件保留。
先确认相关进程已停止；有进行中阶段时不能直接 revise。修改标题从 packaging 回退；修改帧边界从 boundaries 回退；修改剧情从 story 或 openings 回退，不能用包装调整偷改剧情。
后续渲染按节点依赖签名复用未受影响的输出。不能直接编辑已完成阶段文件，程序会检测指纹变化并阻止推进。
本链路是防误操作的工作流，不是文件系统安全沙箱；脱离入口直接运行任意 shell 命令仍可能改文件，执行者必须遵守新目录与只读旧成品边界。
