# 首次使用与环境配置

这是执行者在完整制作前完成的引导，不是新的视频处理阶段。先检查、只提示缺失项、等待用户补齐，再询问制作选项。纯剧本任务无需配置云端 ASR 或渲染工具。已有任务续跑检查其实际依赖，不重新收集已有设置，不修改冻结的工具路径。

## 本地工具：自动定位，不让用户填路径

- 使用 Skill 自身的 `scripts/with_ffmpeg.sh ffmpeg -version` 和 `scripts/with_ffmpeg.sh ffprobe -version` 检查随包工具。当前包支持 macOS Apple Silicon，路径相对 Skill 自动解析；不要求安装另一份 FFmpeg，不回退到其他项目的副本。
- 用 `xcrun --find swiftc` 和返回的编译器路径执行 `--version`，检查包装所需的 Xcode Command Line Tools。缺失才说明需安装；不擅自安装或改系统设置。
- 用 `command -v mediakit-cli`、`mediakit-cli --version` 检查 CLI。缺失时按 `byted-mediakit-shared` 的安装说明引导用户完成；不要自行发明安装方式。安装或初始化须用户同意，不因检查而覆盖已有设置。
- 平台不支持、随包文件丢失或工具无法执行时明确报告原因，停止完整制作；用户仍可选择纯剧本方案。

## MediaKit：只补必要的云端配置

先读取 `byted-mediakit-shared` 与当前 CLI 的 `init --help`、`config --help`，遵循实际版本的鉴权合同。当前 CLI 要求运行时提供 `MEDIAKIT_API_KEY`，不接受通过 init flag 传入，也不会把密钥持久化到 CLI config。

仅检查当前执行环境是否有非空密钥，输出状态，不读取或打印密钥值：

```sh
if [ -n "${MEDIAKIT_API_KEY:-}" ]; then
  printf 'MediaKit credential: present (not verified)\n'
else
  printf 'MediaKit credential: missing\n'
fi
```

缺失时告诉用户：“请在运行本 Skill 的本机环境中配置 MEDIAKIT_API_KEY，完成后告诉我；不要把密钥发送到聊天里。”由用户通过本机安全的凭据管理或环境注入方式设置，使执行 Skill 的进程能继承该变量，再重新检查。另一终端里设置变量不代表当前执行进程已经获得它；不要因此反复要求用户提供密钥。

默认使用 CLI 既有 Cloud endpoint，不额外询问地址。仅当用户明确需要自定义服务地址时，按当前 CLI 支持的选项配置。不要要求与本流程无关的 API 密钥。

不把密钥写入运行 JSON、Skill、仓库、日志、命令行参数或交付包，不打印完整环境变量或凭据文件。只记录工具版本、配置是否存在及脱敏状态；诊断输出确认不含秘密后才能保存。

## 检查结果与启动边界

区分以下状态：工具可运行、凭据缺失、凭据存在但未验证、云端鉴权已验证。变量存在、CLI help 成功或本地 doctor 成功，都不证明云端鉴权有效。

只在当前 CLI 明确提供不上传素材、不创建处理任务的鉴权检查时使用该入口；没有则报告“凭据已配置，云端鉴权待正式调用验证”。禁止猜测接口、用实际素材上传或收费 ASR 任务测试配置。网络错误也不能直接判定为密钥错误。

工具就绪且凭据存在即可进入制作选项确认，但不得宣称云端已验证。正式 ASR 按原规则提交，鉴权失败时保留真实错误、停止并引导修复，不静默更换服务或重传任务。新建 ASR 会把素材交给 MediaKit Cloud，正式处理前明确告知用户。

给用户的检查摘要只列简短状态和需要操作的缺失项。用户补齐后继续，不重复询问已确认的制作选择。
