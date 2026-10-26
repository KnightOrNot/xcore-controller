# xcore-controller 历史交接记录

本文件由 AGENTS.md 拆分而来，保存各阶段实施检查点、真机修复记录和被取代的方案。
内容与当时一致，未作改写；当前生效的规则和状态仍以 AGENTS.md 为准。

## 2026-10-21 首次全量提交

2026-10-21 用户要求将当前全部项目改动 commit。SDK 的共享限位、拒绝启动错误传播、
保存姿态返回及配套测试／文档已提交为 `1d8474d`。
控制仓库将相机子模块、统一 scripts 入口、停止服务脚本、文档和测试一并纳入本次本地提交，
固定上述 SDK 版本。本次未执行 push；后续发布必须先推送 SDK，再推送控制仓库。
现场标定、退出姿态 JSON、日志、数据、虚拟环境仍不纳入 Git。

## 2026-10-26 LeLab 网关、Pull 按钮与网页 finish 等待

- LeLab 原 Upload 改为本地拉取入口：本地网关 `dataset_browser.py` 在 8090 提供浏览，
  内部 SSH 隧道改用 8091；新增 `/upload` 本地页面、服务端注入的“数据集工具”工具栏，
  以及 `export` 入口按来源摘要生成缺失的 pose10／joints 版本。
- 网页“结束会话”改为等待本次会话转换、校验并发布成功后才解锁；调度器读实际 job
  状态并对发布目录执行 `integrity.verify`，不再以 jobs CLI 零退出码作为完成依据。
- 复用本地网关时第 5 步 502：`setup-session dataset` 每次幂等启动远端 dataset unit，
  以 `/api/xcore/pulls` 识别新网关；上游断开时网关只恢复数据服务，不启动硬件。
- 网页模式 `--enable-motion` 只授权网页“启动跟随”按钮，不再在打开页面前激活／
  prepare／arm；未进入跟随就关闭页面用 `shutdown mode=none`，避免 return_mode
  变成第一次运动。终端模式行为不变。
- 验证：controller 146 项、dataset 22 项通过，Ruff、脚本语法、`config_defaults --json`
  通过。`tests/test_*.cjs` 需要 jsdom，本机未安装，未执行；DOM 交互结论沿用 codex
  当时的记录，不能当作在本机复验。真实网页点击、真机 arm／返回／下电仍未验收。

### 2026-10-22 实施检查点（最新状态，未完成完整目标）

本次用户授权检查已连接硬件并开始实现待办；已进行只读硬件测试和首阶段开发／部署。
详见 [阶段说明](docs/REMOTE_DATA_MILESTONE.md)，后续 AI 接续实现时先读该文件。

| 范围 | 已实现／实测 |
| --- | --- |
| 硬件 | GELLO ID1～7 只读在线；CR7 本地及远端 SDK 0.7.1 连接正常，manual/off/idle；夹爪实际反馈正常 |
| 双 D435i | 两台 640×480 RGB＋Z16 同时 10 秒各推进 150 帧，约 15 FPS，USB 2.1；测试后停止采集 |
| 夹爪修复 | 从旧手动服务切到已有独立连续服务；RS485 unit 路径改为 DABGMMQO，--no-activate，未运动；原 unit 已备份 |
| controller | 新增轻量根 uv 环境和 `src/xcore_controller/`，本地 GELLO 只读服务／远端只读 SDK worker／JSON HTTP 数据桥 |
| 接收状态机 | 拒绝重复／乱序和旧实例；断流锁定、重连不自动 arm；硬件 arm 明确拒绝；没有实现或测试真实停止／运动 |
| 独立项目 | xcore-adapters 和 xcore-dataset 已绑定 GitHub 并注册 controller submodule；数据语义校验、原始封存、时间匹配、LeRobot 转换及清单发布已实现 |
| 数据格式验证 | 真实 writer／loader 回读 EE10 state/action、两路 RGB 视频＋两路米制无损深度、12 维力／掩码、中文 task |
| 远端闭环 | 12 帧明确标记 synthetic 的 raw 在远端转换发布，LeLab 列出／读取 episode，本地 rsync 拉取、SHA-256 校验和 loader 回读通过 |
| 数据浏览 | LeLab 仅浏览；应用补充状态／力／深度统计和灰度深度预览，真实深度字段不改；没有开放合并、上传、删除或运动接口 |
| 新入口 | start_gello_service、start_remote_controller、stop_remote_controller、start_dataset、stop_dataset、pull_dataset，均位于 scripts/ |
| 部署 | 远端 SDK 3.11.16、数据 3.12.14 独立运行环境；只读／模拟 controller 和数据 unit 均按需启动、disabled；现有相机环境不变 |

当前 controller 55 项测试通过，adapter／dataset 合计 7 项离线回归通过；新代码 Ruff、
脚本语法及真实跨机只读数据桥测试通过。共享 converter 及五个既有 submodule 未修改。
本次未上电、未切换机械臂模式、未下发运动、未重新激活／开合夹爪，未自动执行退出返回。
现场测试数据、虚拟环境、SSH 和运行配置不进入 Git。
首阶段检查结束后已停止本地 GELLO／桥和测试隧道，远端只读／模拟 controller、数据浏览、
双相机 unit 均已停止且 disabled；夹爪保持修复后的服务运行、disabled、未运动。
两个新增独立包的 wheel 构建通过，dataset wheel 内默认 TOML 已核实包含。

**仍待完成，不能误报为可用**：

1. 真正的远端 RT 运动迁移、校准映射／分支、限位／对齐／退出策略与真机断流停止验收。
   当前 hardware-read-only 的 motion_capable=false；旧真实跟随仍在本地。
2. 实际机型 FK 与夹爪 TCP 验证。仅确认 vendor 六轴模型 API 可读，未验收工具标定，
   不能用模型输出或法兰坐标静默冒充经过验证的夹爪 TCP。
3. 相机单 pipeline 的无损 RGB／Z16 连续记录分支，以及真实 SDK 反馈／目标和两路力接入。
   当前相机 snapshot 彩色为 JPEG；新转换器只验证已封存的合成 raw，不会补出缺失图像。
4. 跨机源时钟映射／不确定度估计、真实多流协调、session 多 episode／转换任务队列和崩溃恢复。
   当前 LeaderInbox 只验证序号、源时间单调及接收超时，不等同于源帧龄或曝光同步验收。
5. LeRobot Robot／Teleoperator 控制协议适配、完整可复现部署包、
   数据吞吐与长时间测试。当前新工具按 checkout 运行，不能宣称单 wheel 可独立部署。

后续按照上方目标架构推进，保留原七维链和共享 converter。实际运动验收仍需现场人员
明确确认后执行；已连接硬件／只读测试通过不能替代该验收。

用户随后要求停止功能开发：仅完成 GitHub 绑定、submodule 引入、进度记录和 commit／push
后停止。本次交接不继续推进以上待办。先推送两子仓库，再推送父仓库 gitlink；
运行环境、现场数据及既有五个 submodule 不纳入本轮代码改动。
本轮新增子模块基线：xcore-adapters `779b25b`、xcore-dataset `369ca4c`。

## 从首页内部路由进入也保留 Pull（2026-10-26，最新修复）

- 用户明确澄清：直接打开有 Pull，但从 LeLab 首页的数据集入口进入同一地址没有。
  这是文档入口／SPA 复用问题，不是 LeLab 权限禁止新增按钮。
- 网关现在为**所有 LeLab HTML 入口**直接输出固定的“数据集工具 / Pull 到本地”栏，
  位于 React #root 外侧；不依赖匹配 Upload、React 重绘或 DOMContentLoaded 插按钮。
  没有 head 的 HTML 片段也包装成完整文档并加载适配脚本，避免部分入口漏注入。
- 原生 Pull 链接始终存在并在新标签页请求本地 /upload；适配脚本只同步当前版本，
  不把公共栏移回 React 内部，不拦截 LeLab 的路由或原 Upload。
- Python 网关 16 项、DOM 回归通过。额外使用真实 LeLab bundle 实测“查看页 Back
  返回首页 → Select or create a dataset → 选择 session_20261026_155633 → 查看页”，
  公共 Pull 始终为同一 DOM 元素，位于 #root 外侧；点击默认行为不被阻止。
- 最初已加载的旧 LeLab 文档仍须完整刷新一次；之后从该首页内部跳转不再丢工具栏。
  只重载独立数据网关，没有操作数采面板、机械臂、夹爪或相机。

## 独立 Pull 入口（2026-10-26，取代下面 Upload 拦截方案）

- 用户反馈仍进入原 Hub 页，随后明确要求直接在 Upload 旁新增 Pull，优先保证功能。
  本轮改为给查看页工具栏插入独立原生 `<a>`：`Pull 到本地`，位于原 Upload 右侧，
  href 为 `/upload?dataset=<当前版本>`。原 Upload 保留，不再改写它的点击或 React 路由。
- Pull 使用浏览器原生文档导航，不是 React Link；两种表示和路径展示沿用本地拉取页。
  数据集切换／页面回退后更新链接，旧工具栏重新渲染后可重新插入。
- 同时发现当前查看页实际返回 502：数采退出停止了远端 dataset，独立本地网关仍存活。
  网关 GET/HEAD 在上游断连时按需恢复 **仅 xcore-dataset.service** 并等待真实就绪后
  重试一次；恢复有互斥和冷却，写请求不重放，不启动 controller／相机／夹爪或跟随。
- 独立网关已在无传输时重载。13 项网关测试、DOM 回归通过；使用现场真实 LeLab
  bundle 验证 Upload 仍在、原生 Pull 相邻、点击未被 React preventDefault、目标页
  HTML 正确、自动选中用户的 session_20261026_155633/rev-0001 及 pose/joints 两选项。
- 浏览器控制工具仍无可用浏览器；以上为真实 bundle 的 DOM 集成与 HTTP/API 验证。
  最新静态脚本由网关按请求读取，重新完整打开查看页才能替换旧文档中的代码。
- 已实测停止仅远端 dataset unit 后，直接 GET 本地 `/api/datasets` 在约 3 秒内自动
  恢复并返回 7 个发布版本；未操作 controller／相机／夹爪。当前查看页与 /upload
  均可经新网关正常读取。

## Upload 两个入口统一（2026-10-26，最新网页行为）

- 用户指出查看页经 React 内部路由进入的 /upload 与直接打开不一致。查看页原
  Upload 按钮现在阻止原 React 跳转，执行完整文档导航到
  `/upload?dataset=<当前版本>`；不再另开查看页专用弹窗。
- 两个入口由网关提供完全相同的 `lelab_upload.html` 和 `lelab_pull.js`，从查看页
  进入自动选中当前数据集，pose/joints 选择、拉取状态和路径展示共用一套页面。
  SPA 进入旧 /upload 的兼容路径也强制完整导航；不修改上游 LeLab bundle。
- 10 项网关测试及 DOM 回归通过；额外使用现场真实 LeLab bundle 与用户提供的
  `session_20261026_155633/rev-0001` URL，验证原按钮完整导航、两入口 HTML 相同、
  当前版本自动选中及两种格式。只读取元数据，未启动硬件或重新拉取现场数据。
- 本次仅静态 JS 改动，当前本地网关按请求读取文件，刷新查看页即加载新行为；
  无需为此重启正在进行的数采。旧页面中已经加载的 JS 不会自动替换。

## Finish 等待数据完成保护（2026-10-26，最新功能）

- 用户确认最近数据并未丢失，是 finish 先返回、转换成品尚未发布；要求完成前锁住
  按键。本轮停止继续排查缺失数据，改为 finish 等待保护，不移动机械臂。
- 网页 finish 在 session/stop 排队后，持续等待**本次 session** 的转换完成；操作
  job 保持 running，显示“转换、校验并发布数据集”。只有 verified=true 且有发布
  路径才显示“已保存并发布”并完成任务；失败显式报告，不能拿旧 session 的 ready 通过。
- 前端和服务端同时检查转换 queued/running；刷新页面仍不能开始下一轮。等待超时
  或断线不等于转换取消，远端仍 running 时按钮继续锁定，状态不可靠时也不开放。
- ConversionScheduler 不再仅凭 jobs CLI 的零退出码标为 ready；读取本次持久 job，
  检查 ready，并校验发布目录的 READY 清单及 SHA-256，再返回 verified/path。
  LeRobot loader 回读仍由原转换器发布前执行，未把转换依赖导入 SDK 环境。
- controller 136 项回归及实际 PAGE 的 DOM 状态检查通过；覆盖等待锁定、刷新、超时、
  失败、非本次会话、缺失／损坏 READY 和最终解锁。代码已同步远端，备份在
  `~/.local/state/xcore-finish-guard-20261026T155158/`。
- 当前用户数采进程未强制重启，仍持有旧模块；需要退出并重新运行数采命令才会同时
  加载新的本地网页后端和远端调度器，单纯刷新浏览器不更新 Python 模块。

## 用户授权六轴回零完成（2026-10-26，最新姿态）

- 用户明确要求“回到 0 位”。确认所有 controller unit 停止、持有 `.follow.lock`、
  operation=idle、软限位开启且当前／零位均合法后，执行一次 NRT MoveAbsJ 六轴回零。
  使用现场 return 参数 speed=1000 mm/s、timeout=600s，先切 NRT 再 automatic／上电，
  不重复切模式；没有启动跟随或操作夹爪。
- 起始角度约 `[3.5193,-21.7780,-2.3832,-2.2420,4.0414,-0.4254]°`。
  回零后下电实测约 `[-0.00055,-0.00195,0.00584,-0.00010,0.00573,0.00073]°`，
  最大绝对误差 0.00584°，结果 reached_zero=true。
- 最终状态 idle／off／manual。下方“RT 恢复未执行返回”描述的是此前恢复步骤，
  当前姿态以本段已完成的用户授权回零结果为准。

## 残留 RT 状态已恢复（2026-10-26，最新现场状态）

- 用户明确要求立即执行退出残留实时控制命令。确认 hardware/readonly/simulate unit
  停止后，持有同一 `xcore-sdk-python/.follow.lock`，用远端 SDK 3.11 调用已有
  `xcore_sdk_python.return_zero.recover_rt()`，没有调用 return_pose/return_zero。
- 执行前：operation=rtControlling、power=off、mode=automatic；执行 RT stopMove、
  一次 automaticErrorRecovery、切 NRT、stop 后，下电并切 manual。
  执行后：operation=idle、power=off、mode=manual，recovered=true。
- 没有启动 RT loop、arm、prepare、关节目标或返回运动。两次读数的最大关节变化
  约 2.40e-7 rad。下方记录的 rtControlling 阻塞现已解除，不再沿用“只能示教器恢复”
  的结论；恢复使用已有明确的 SDK 停止路径，不能绕过 idle 门限直接开始运动。
- 启动数采网页仍只准备组件，跟随由用户点击网页“启动跟随”触发；本次未自动重启
  hardware 服务或代用户点击启动。

## 后续反馈修复：502、网页手动跟随与 /upload（2026-10-26）

- 用户实际命令为 `start_remote_record.sh --task "pick and place" --web --enable-motion`。
  第 5 步 502 的原因是数采退出停止了远端 dataset unit，但独立本地网关依然存活，
  脚本误把本地 `/api/xcore/pulls` 健康当成远端服务已运行。`setup-session dataset`
  现在每次幂等启动远端 dataset unit，再经 `/api/datasets` 等待真实就绪。
- 用户明确要求网页按钮决定何时跟随，取代此前网页打开前自动激活／prepare／arm 的
  要求。网页启动现在只准备组件及桥；`--enable-motion` 只允许网页按钮。终端模式
  的显式确认流程保持兼容。未启动或启动失败就关闭网页时使用 `shutdown mode=none`，
  不能因默认 return_mode=zero 产生第一次运动。
- `/upload` 由本地网关直接提供独立拉取页面，可选远端已发布数据集及 pose/joints。
  查看页 Upload 接管不再依赖 SVG 类名；支持脚本在 DOMContentLoaded 后加载及 SPA
  进入 /upload，避免原上传页重定向／Hub 登录流程。旧浏览器文档需完整刷新加载脚本。
- 修复后五阶段 `--check-only` 真机服务就绪检查通过；实际网页命令启动后读取状态为
  idle、armed=false、session=null。未发送 prepare、arm 或关节目标，未做运动验收。
  验证面板已关闭以释放入口锁；关闭结果无返回动作，远端组件按 --keep-services 保留。
- 不能把上述应用 idle 当作控制器硬件已空闲：测试面板关闭的 shutdown 返回
  `mode=none, returned=false, powered_off=false`，原因是厂商 operationState 仍为
  `rtControlling`。15:06 日志存在旧 RT hasMotionError 后回调未在 3s 内结束、随后
  systemd SIGKILL 的历史；本轮没有重新 arm 或自动切换／恢复旧 RT。需现场在示教器
  确认停止并按控制器流程恢复模式，不能宣称下电／真机跟随已恢复。
- 最终 controller 128 项回归、Ruff、shell 语法及 DOM 检查通过。启动与网页修复已
  同步远端源码，原文件备份为 `~/.local/state/xcore-web-pull-fix-20261026T152412/`。
- 使用真实安装的 LeLab bundle 和用户精确的 session_20261026_130329 查看页 URL
  在 DOM 环境验证按钮／格式弹窗；实际 /upload HTML＋API 的 joints 拉取及路径显示通过。
  浏览器控制工具仍不可用，不把 DOM 集成验证称作真实浏览器视觉验收。

## 本轮最新范围：LeLab 网页拉取（2026-10-26）

- 用户暂不修改保存耗时及停止统一转换，只实现 LeLab 原 Upload 按钮拉取到本地，
  弹窗选择 `--pose`／`--joints`，校验成功后显示本地绝对路径。保存／停止／自动转换
  调用链保持原样；converter 仅增加显式格式导出所用的可选来源摘要检查，默认行为不变。
- `start_dataset.sh` 现在在本地 8090 提供浏览代理和拉取任务，SSH 内部隧道使用
  `roles.dataset_tunnel_port=8091`。数采入口按 `/api/xcore/pulls` 识别新网关；旧隧道
  需先退出。`dataset_browser.py`／`lelab_pull.js` 是本项目的包装层，不修改上游 LeLab。
- 弹窗选中另一种表示时经 SSH 调用 dataset `export`：校验当前发布版 READY、原始
  COMMITTED 摘要、完整片段列表和来源，生成独立的来源摘要命名版本；重复请求复用，
  缺字段拒绝。CLI 原 `pull --pose/--joints` 语义不变，网页复用其 rsync／校验／回读。
- 远端只部署 dataset `export.py`、`cli.py`、`convert.py`，原文件备份在
  `~/.local/state/xcore-lelab-pull-20261026T145130/`。只启动数据服务和本地网关，
  没有启动 controller、相机或夹爪。
- 离线 controller 122 项、dataset 22 项通过；额外 DOM 集成检查验证按钮拦截、
  pose/joints 选择、路径展示和 SPA 切换。无可用浏览器工具，未做真实浏览器视觉验收。
- 真实 `session_20261026_135606/rev-0001` 经同一网页 API 拉取 pose10 56 帧成功；
  joints 导出并拉取成功，版本 ID 为 `session_20261026_135606-joints-d6b8cd54e1de`。
  两者 SHA-256 和本地 loader 首尾回读均通过，保存在本地 `data/lerobot/`，不入 Git。
- 当前修改未 commit／push。同级 `../xcore-dataset` 仍是较旧独立 checkout，不能
  将其覆盖回集成子模块或远端。本地网关需要保持启动进程存活，退出清理仍沿用旧逻辑。


## 配置与文档改造交接（2026-10-21）

已完成并通过审查：

- controller 与五个 submodule 均新增 `config/default.toml`、配置加载模块和覆盖入口：
  SDK/夹爪/转换器用 `--config`，相机用 `--defaults`（`serve --config` 仍是现场 JSON），
  GELLO 用 `XCORE_GELLO_CONFIG`。
- controller 新增 `tools/config_defaults.py`；七个 shell 入口读取 TOML，
  `setup.sh --check-only` 校验六份配置文件存在。
- 文档骨架对齐 agilex：controller 新增 `docs/index.md`、`docs/installation.md`、
  `docs/cameras.md`、`docs/reference/{cli,config,errors,submodule-config}.md`、
  `CHANGELOG.md`、`CONTRIBUTING.md`、`THIRD_PARTY_NOTICES.md`；五个 submodule
  补齐 `docs/` 和根文档，README 增加配置与文档入口。
- 现场文件仍不进入 Git：`cr7_calib.json`、`exit_pose.json`、远端 `camN.json`、
  数据集、日志、截图。

验证结果（全部离线，未连接机械臂、未启动相机采集、未操作夹爪）：

| 范围 | 结果 |
| --- | --- |
| SDK | 214 passed；Ruff 和格式检查通过 |
| controller | 53 passed |
| 夹爪 | 45 passed + 6 subtests |
| 转换器 | 7 passed |
| 相机 | 18 passed |
| GELLO | 16 passed（`tests/`，不包含未使用的 ROS2 工程） |
| 其他 | 五个 wheel 均包含默认配置；SDK sdist 包含配置；Python 3.8 GELLO、Python 3.10 GELLO/夹爪配置导入通过；配置工具、脚本帮助、`xcore doctor` 和变更文档链接检查通过 |

审查修复：

- 默认截图采用每次独立时间戳目录，重复调用不因目录已存在失败。
- controller 配置的夹爪端口传入 SDK 跟随入口，显式 CLI 仍优先。
- 直接 SDK 准备／返回命令保持历史默认 1000 mm/s；controller 仍按其配置显式传入速度（当前 4000 mm/s）。
- GELLO Python 3.8–3.10、夹爪 Python 3.9/3.10 使用条件依赖 tomli，保持原声明兼容性。
- SDK 的 --config、相机的 --defaults 支持子命令前后；拒绝非法配置类型、端口、非有限数值，检查 shell 环境覆盖值。
- 配置或工具单独缺失时在设备操作前报错；第三方说明不自行声明未知的厂商再分发禁令。

本轮本地离线测试合计 353 项及 6 个 subtests。用户已授权本轮 commit 与 push；
顺序是先五个 submodule，再更新父仓库指针并提交／推送 controller。
未执行远端部署或真机操作，相机和夹爪的现场硬件状态未因本次审查改变。

尚需人工验收：真实跟随、退出返回、夹爪实际开合、相机页面排版与按钮交互。
夹爪 RS485 适配器当前不在远端，硬件恢复前保持 `xcore-gripper-follow.service` 停止。

### 用户要求与参考流程

用户已要求：**采集后在远端转换为 LeRobot 格式，使用 LeRobot、LeLab 和自编 adapter，
本地需要时再经网线传回数据**。随后进一步确认：**将 SDK 控制也迁移到远端，
本地只保留 GELLO 服务与操作客户端**。后续实现以此为目标，取代之前
“本地 SDK 控制并上传记录副本”的中间方案，不再以本地控制为新链路主架构。
**当前真实跟随仍是本地 GELLO＋本地 SDK；远端已部署只读 SDK worker，真实跟随迁移尚未完成或验收。**
既有流程保留兼容，但不得与新远端流程同时控制同一机械臂。

已只读参考 `../agilex/agilex-controller/` 的这些实现（相对 `xcore/` 根目录）：

- `README.md`、`docs/index.md`、`docs/cameras.md`：存在“CLI raw 后转换”和
  “浏览器直接写 LeRobot”两条并行链，原始数据、输出和环境分离。
- `src/agilex_data_collection/session.py`：通过 `LeRobotDataset.create/add_frame/`
  `save_episode/finalize` 写数据，保存原始 RGB/Z16、标定和采样审计。
- `agilex-adapters/src/agilex_adapters/{devices,transport}.py`：LeRobot
  Robot／Teleoperator 协议与硬件 worker 分离，adapter 不拥有底层设备。
- `src/agilex_data_collection/runtime.py`：集成 LeLab 数据集浏览和管理，数据根目录一致。

参考工程的浏览器链是直接写入而非再次调用旧 converter；本项目选择先完整保存 raw，
再在远端后台转换，以便重试、核查同步和避免编码影响实时跟随。
**LeRobot 负责数据集格式和写入／读取；LeLab 负责浏览、回放和管理，不是转换引擎；
自编 adapter 负责 CR7 数据语义、同步和字段映射。** 不照搬 PiPER 的七维 schema、
CAN 初始化、回零逻辑或同机时钟假设。

### 拟定组件、目录和运行环境

| 组件 | 位置／职责 |
| --- | --- |
| controller 本地角色 | GELLO 服务生命周期、远端命令客户端、SSH 管理／隧道、预览入口及按需拉取；不连接 CR7 SDK，不拥有运动循环 |
| controller 远端角色 | 设备 worker 与会话编排、GELLO 接收／映射、跟随启停／对齐／退出策略、采集协调及数据任务调度 |
| xcore-gello-software | 本地唯一 GELLO 串口 owner，只读六轴／扳机并发布带序号和时间的反馈；不控制从臂 |
| xcore-sdk-python | 迁移后由远端唯一 SDK worker 拥有 CR7 会话、实际反馈、限速／插值及实时下发；现有本地 SDK 链仅作兼容入口 |
| xcore-gripper-2F85／远端夹爪服务 | 远端夹爪唯一串口 owner；由远端会话使用同一次 GELLO 采样驱动目标并记录实际反馈 |
| camera-realsense-d435i | 远端两台相机的唯一 pipeline owner；增加 RGBD 原始帧记录分支，与预览共享采集 |
| xcore-adapters（独立子模块） | 独立适配包：CR7／GELLO LeRobot 协议、采样数据契约、FK／EE10、特征和深度／力字段映射；不直接另开 SDK／串口 |
| xcore-dataset（独立子模块） | 远端记录会话、raw 写入与封存、时间对齐、LeRobot 转换任务、质量报告及 LeLab 集成；依赖 xcore-adapters，与 controller 通过明确接口协作 |
| LeRobot／LeLab | 远端独立数据环境中的锁定依赖；数据处理应用调用其 API，不改上游代码 |

新增项目源码在本地 `xcore/xcore-adapters/`、`xcore/xcore-dataset/` 独立维护，
controller 已通过同名 submodule 引用两个 GitHub 仓库并集成有限入口。
远端仍是本轮部署的开发快照，不能把 GitHub 发布等同于完整功能或部署自动化已验收。
远端部署在 `~/project/xcore-adapters/`、`~/project/xcore-dataset/`，
业务数据统一放 `~/project/xcore-data/`，与代码／虚拟环境分开并排除 Git。
远端还需部署同一仓库的 `~/project/xcore-controller/` 及所需 SDK 子模块，
以远端角色运行；本地 checkout 运行本地角色。通过明确的子命令／角色配置选择，
不靠主机名猜测，不维护两套源码或重复默认值；实际 CLI 名称在实现时统一确定。
本地角色的安装／启动不应要求加载 SDK 二进制或安装 LeRobot 重型依赖；
远端不因配置中存在 GELLO 路径而尝试打开本地同名串口。

```text
~/project/xcore-data/                 # 拟定远端数据根目录，可配置
├── raw/<session_id>/                 # manifest、episode、状态/目标、双 RGBD、两路力、时钟审计
├── staging/<job_id>/                 # 未完成的转换输出，不供 LeLab 或本地正式使用
├── lerobot/<dataset_id>/<revision>/  # 校验完成、不可变的数据集版本
├── reports/<job_id>/                 # 质量报告、错误、任务与源 raw 标识
└── logs/                            # 接收、采集、转换及服务日志
```

LeRobot／LeLab／adapter 采用独立 Python 3.12 环境作为参考起点，依赖版本和 CPU
Torch／FFmpeg／视频后端以远端兼容性测试及 `uv.lock` 固定，不盲目追最新版。
SDK worker 保持 CPython 3.11／Linux x86_64 ABI，迁移前在远端独立验证；
远端现有相机环境保持独立，不为数据工具改其 Python ABI。
`~/project/xcore-runtime/` 是生成的运行环境目录，存放 Python、vendor／venv 和视频库，
不承担设备控制、数据适配或采集业务，不应变成第四个业务源码项目。
其可复现安装脚本／依赖清单由 controller 的 deploy 或对应独立项目维护，环境本身不进 Git。
参考工程当前锁定 LeRobot 0.6.0 和 LeLab 提交
`9b5afaee33baa1d773e499937564f3831d25de22`，仅作为已检查的参考组合，
部署前需在远端验证双 RGBD、12 维力、有效掩码和字符串的真实写入／读回。

### 本地与远端的控制边界（后续实现必须遵循）

```text
本地 GELLO 只读服务 ── 有线网络／受限通道 ──→ 远端 controller
本地操作客户端    ── 启停／采样／保存命令 ──→   ├─ SDK worker → CR7
                                                ├─ 夹爪服务
                                                ├─ 双 RGBD／两路力 → raw
                                                └─ adapter → LeRobot → LeLab
本地预览／数据目录 ←─ SSH 预览／按需拉取 ───── 远端状态及已发布数据集
```

- **GELLO 数据面**：本地仅发布六轴／扳机反馈、源时间、序号、采样有效性和服务实例标识。
  远端执行映射、2π 分支、标定、限位及起始对齐检查，六轴与夹爪共用一次主臂采样。
  标定版本及原始读数语义需在握手／manifest 明确，避免两边重复加 offset／sign。
- **实时控制面**：远端接收最新有效目标，远端 SDK worker 在本机执行限速、加速度限制、
  插值与 SDK 实时下发；RT 回调不能等待网络、编码、LeLab 或写盘。
  网络输入频率与 SDK 实时周期分开配置并实测，不能承诺经普通网线达到硬实时同步。
- **命令与权限**：本地发送的是启动／停止／记录等请求，远端会话状态机最终决定是否执行。
  浏览页面、查询状态、启动 API、转换或下载都不能隐式启用运动；运动准备／启用仍需
  明确操作和对齐验收。生命周期由远端 controller 管理，不由 LeLab 或 adapter 偷启设备。
- **断流与重连**：远端监测主臂帧龄、源有效性、连接心跳及控制 worker 状态；拒绝旧实例、
  乱序、过期和无效数据。目标数据使用有界“最新值”通道，不能积压后补放历史动作。
  GELLO 断流／断网时由远端触发经过验证的停止／保持策略，夹爪流也必须有超时处理；
  不能无限保持最后一个运动指令。恢复连接后重新握手、检查两臂姿态并显式启用，
  不自动续跟随、不因断流自动执行返回姿态。具体 SDK 停止／保持行为需离线及现场验收。
- **数据记录面**：实际机械臂反馈、已接受目标、夹爪及相机／力在远端采集和落盘；
  接收的原始 GELLO、源时间和接收时间另保留以审计网络延迟。记录副本通过队列从唯一
  控制 worker 分出，不能开第二个 SDK 会话。审计数据可以补传／去重，控制目标不得补放。
- **所有权与兼容**：同一时刻只允许一个 GELLO 串口 owner、一个 CR7 SDK 控制 owner
  和一个夹爪串口 owner；本地旧跟随与远端新跟随互斥。远端文件锁不能独自防止旧本地
  进程竞争，切换前必须确认旧会话已完全退出，并让新本地入口不再连接 SDK。
  停止数据服务不能顺带重启整机或夹爪；退出返回属于真实运动，必须沿用明确配置和授权，
  不照搬参考工程的自动回零。

### 端到端流程与数据完整性

1. **按需准备**：本地启动 GELLO 只读服务，并通过 SSH 按需启动远端 controller、
   数据服务、必要的相机服务及隧道；建立角色／会话握手并检查旧控制会话已退出。
   查询磁盘空间、依赖、两台相机和时钟质量。沿用不开机自启的约定；启动数据浏览／转换
   不隐式上电机械臂、激活夹爪或启动跟随。浏览和离线转换不需要相机在线。
   远端 HTTP 绑定 loopback，本地经 SSH 隧道访问；同机 worker 可用私有 Unix IPC，
   跨机使用明确 schema 的受限传输通道，不把 pickle IPC 直接暴露到网络。
2. **建立 session**：分配唯一 session／episode ID，记录任务字符串、设备 serial、
   模型／TCP／标定、完整字段定义、各流 profile、数据频率、时间映射和代码版本。
   新 raw 标记独立格式／版本，不能冒充旧七维 converter 输入。
   数据频率独立配置，先按实测最慢必需流确定；样例约 10 Hz 只是起点，不构成已确认指标，
   不能照搬 agilex 的 30 FPS，当前双 D435i 共用 USB 2.0 带宽。
3. **远端控制并记录**：本地只发送带序号和源时间的 GELLO 数据。远端经显式启用后
   映射主臂目标并在本机下发 SDK，同时从唯一 worker 输出实际关节、TCP／夹爪反馈、
   请求／接受／插值目标及其时间信息；原始主臂样本也进入审计。
   远端同步记录两路力（未接入力时掩码为 false），相机原始 RGB/Z16 直接在远端落盘，
   不先传回本地再上传。writer 按 session＋序号接收、去重并确认持久化；
   必要的审计重试与运动目标通道分开，禁止为补数据重新执行历史动作。
   网络和磁盘不阻塞 RT；录制队列满、断流、重传缺口或写盘错误须显式标记当前集失败，
   不能静默丢失后还宣称完整。记录失败与跟随停止策略分别明确，不由记录器擅自触发回零。
4. **保存／丢弃 episode**：本地发命令，远端用同一 episode ID 协调机械臂、夹爪、
   主臂审计、两台相机与力数据流；设备各自采集时间独立，不把控制消息同时到达当作硬同步。
   保存时先截断采样范围并等待所有必需流持久化确认、写队列排空、索引和文件落盘，
   校验连续性后最后发布 episode 的提交标记。只有这个标记存在才进入转换队列。
   活动集使用 `.partial` 或等价状态；异常／断电／缺流不生成完成标记。
   丢弃不进入训练集，按配置保留审计；停止或关网页不会自动保存未确认片段。
5. **远端后台转换**：对已封存的 raw 做只读快照，按会话生成数据集；默认在 session
   结束后排队，也支持手动重试，避免与采集争用 CPU／磁盘。建立可配置目标时间轴，
   state 与 action 保留同一原始记录的对应关系；四路图像及两路力独立匹配并输出误差。
   明确最近帧／等距选较早帧等规则、复用数量和阈值；不通过无限重复旧图伪造采样率。
   远端数据使用明确的主机时间域；相机设备时钟映射到该时间域，本地 GELLO 另做跨机
   偏移／漂移与不确定度记录，不能直接比较两机 monotonic；不把软件对齐宣传为硬同步。
   必需流超时差／缺失或旋转无效时拒绝发布；预留力未安装是合法的无效掩码状态。
6. **验证并发布**：adapter 产出下表字段，LeRobot API 写入 staging；编码、
   `finalize`、真实 loader 读回和质量检查全部完成后，生成文件清单／大小／SHA-256、
   源 raw 标识、依赖版本和 `READY` 标记，再在同一文件系统内原子发布为不可变 revision。
   质量报告包括采样率、重复／缺失帧、各流误差和时钟不确定度、深度范围、力掩码与数量。
   失败保持原 raw，保留 staging／错误供排查；重试写新目录，不能覆盖已发布数据集。
   转换任务记录 queued/running/failed/ready，重启可恢复，不能仅凭进程退出码宣称数据完整。
7. **LeLab 查看与管理**：只列出已发布的数据集根目录，通过 SSH 页面浏览 episode、RGB、
   状态及支持的深度视图；启动时设置统一数据根目录，避免意外读取默认 HF 缓存。
   自定义深度／力特征若官方页面不能展示，由应用补充查看，不删除真实字段来适配页面。
   编辑／合并产生新 revision，源 raw 与已发布版本不改；首次必须验证合并保留双深度、
   任务、力字段与元数据。Hub 上传或删除不属于当前默认流程，不能自动发布或清理数据。
8. **本地按需拉取**：用户指定 dataset ID／revision，由本地经有线 SSH 使用 rsync
   拉取整个已发布目录（Parquet、视频／深度、meta、报告、校验清单），不是只复制一个 parquet。
   写入本地 `data/lerobot/<dataset_id>/<revision>.partial/`，支持断点续传；
   全部文件按远端清单核对大小和 SHA-256，并用本地兼容 loader 回读后才改为正式目录。
   中断保留 partial 供续传，失败不假报成功；禁止默认 `--delete` 或传完删除远端源数据。
   未完成／正在改写的 revision 不允许拉取。数据传输与预览分离，训练数据不经 MJPEG。
   原始数据只在显式 `--include-raw` 请求时拉取，默认只拉取完整 LeRobot 成品及元数据。

### 本地拟定脚本与验收顺序

以下是完整目标的入口设计；2026-10-22 已实现的有限入口见文末检查点，其余仍待实现。
不能把只读 SDK 数据桥当作可启用运动的跟随入口。实际实现时同步 CLI、
`config/default.toml`、README 和测试，不在 shell 里复制默认参数：

| 拟定入口 | 用途 |
| --- | --- |
| `scripts/start_gello_service.sh` | 本地启动只读 GELLO 服务，发布主臂数据；不连接 CR7 SDK |
| `scripts/start_remote_controller.sh` | SSH 按需启动远端 controller／worker API，建立连接并查询就绪状态；不隐式启用运动 |
| `scripts/start_dataset.sh` | SSH 按需启动远端记录／数据管理 API，建立 LeLab 隧道；不启动运动 |
| `scripts/stop_dataset.sh` | 停止自有数据服务／隧道；有活动采集或转换时拒绝直接停止，先正常结束任务 |
| `scripts/start_gello_follow.sh` 新模式 | 本地请求远端完成准备与跟随，运动显式启用；旧本地 SDK 模式单独选择并互斥 |
| `scripts/start_data_record.sh` 新模式 | 集成本地 GELLO 服务、远端 session／跟随、任务、采样／保存／丢弃及远端完成确认，旧七维入口保持兼容 |
| `scripts/convert_dataset.sh SESSION` | 触发／重试远端转换，查询任务和质量状态；不调用旧 lerobot-converter |
| `scripts/pull_dataset.sh DATASET REVISION` | 经有线 SSH 断点续传成品、校验并在本地发布，可显式附带 raw |

按以下顺序推进，不在文档阶段创建服务或自动部署：

1. 先确定独立包与 raw/schema，使用双 RGBD、EE10 和 12 维力的合成数据完成 adapter、
   LeRobot 写入／读回及 LeLab 浏览测试；保护旧七维和共享 converter 不变。
2. 先完成同一 controller 的双角色、GELLO 只读服务和跨机协议，用模拟 worker 验证
   目标帧龄／乱序拒绝、断流停止、重连不自动续跟随，以及旧／新控制链互斥。
   对远端 SDK 的 Python 3.11 ABI、依赖、到 `192.168.2.160` 的路由及实时通信所需
   本机地址做检查；只读连接和状态验证与运动验收分开，不照抄本地 local_ip。
   SDK 部署成功不等于已验证远端控制性能。
3. 完成远端 worker 采样到 raw、审计序号去重／重传、时钟映射和 episode 提交协议；
   测试断网、重复包、队列满、磁盘失败、保存中断和进程重启恢复。
4. 实现离线转换任务、质量报告和不可变发布；验证四路图像同步、深度单位、任务文本、
   action 对应关系、力掩码及 LeLab 操作后的特征完整性。
5. 用合成已发布数据验证 rsync 首次拉取、断点续传、篡改校验失败、重复拉取与原数据保留。
   实测有线带宽／磁盘吞吐，不假设网口一定为千兆，也不承诺未测的实时图像吞吐。
6. 最后在旧本地 SDK 会话完全退出后，单独安排现场远端控制、断流停止和小段采集验收，
   再做持续吞吐与同步误差测试；离线测试不能替代运动与停止行为验收。
   新采集所需的运动测试必须由现场人员确认并启动，不因数据部署自动运行跟随或退出返回。

## 退出返回模式交接（2026-10-22）

- controller `config/default.toml` 新增 `[robot].return_mode`，默认 `zero`：
  直接返回六轴 0°；`start` 模式在启动跟随／记录前通过只读 `xcore capture-pose`
  记录当前六轴反馈，退出时返回该姿态；`none` 不返回。命令行 `--return-mode` 和
  `XCORE_RETURN_MODE` 优先。
- SDK 新增 `capture-pose --save FILE [--zero]`：前者只读记录当前反馈，后者生成零位目标
  且不连接设备；文件仍为 `schema_version=1`、匹配 `robot_ip` 和六个 `joints_rad`。
- SDK 启动器新增 `--return-mode`；正常客户端退出、SIGTERM 与 Ctrl+C 都会请求返回，
  只读预览不返回。会话目标写入 `logs/follow-*/exit_pose.json`。
- 已更新 controller README、`docs/index.md`、`docs/reference/{cli,config}.md`、
  SDK `docs/reference/{cli,config}.md` 和两处 CHANGELOG。
- 离线验证：SDK 跟随启动器 48 项（含 start/zero/none/非法模式）和 CLI capture-pose
  测试通过；controller 配置测试与完整离线测试通过。未上电、未启动跟随、
  未执行退出返回，真机返回路径仍需现场验收。

## 数采全流程实施检查点（2026-10-22，分阶段进行）

用户要求按本文分配实现完整数采链路，每完成一个阶段汇报。以下记录代码、离线测试
与真机只读／采集验证的区别；运动验收仍需现场人员明确确认。

### 阶段 1：相机无损 RGB／Z16 连续记录（已完成）

- 相机子模块 `76d33ac`：`recorder.py` 从唯一 `CaptureManager` pipeline 取样，
  采集线程只入有界队列（`serve.record_queue`，默认 16），独立线程以 PNG
  `compress_level=1` 写无损 RGB，并直接复用已编码的 Z16 PNG；帧索引记录双流帧号、
  SDK 时间戳／domain、主机接收时间。目录受 `serve.record_root`
  （`~/project/xcore-data/raw`）限制，`COMPLETE.json` 才是完整标记。
- 队列满或写盘失败会把片段标记为 `failed`；`stop` 设备时自动以失败状态结束记录。
- 离线测试 23 项通过（新增长度、目录边界、失败标记、HTTP 记录接口）。
- 远端已同步源码与 `config/default.toml`、重启两个 loopback API；真实双机
  10 秒记录各 150 帧、`dropped=0`，RGB `uint8 (480,640,3)`、深度 `uint16
  (480,640)`、接收时间单调，测试数据已删除，采集已停止，API 保持 idle。
- 实测 PNG level 6 的 640×480 RGB 编码约 105 ms／帧，无法满足 15 fps；
  level 1 约 21 ms。不要把压缩级别改回默认值而不重新测试吞吐。

### 阶段 2：远端运动 worker、主臂映射与 FK（代码完成，运动未验收）

- `src/xcore_controller/mapping.py`：在远端完成 tick→rad、连续解缠、标定 offset/sign、
  2π 分支和毛刺拒绝；本地 GELLO 仍只发送原始 ticks，远端不重复加 offset。
- `src/xcore_controller/motion.py`：唯一 SDK 线程；显式 `/arm`（新鲜样本＋对齐门限）、
  `/prepare`（静止采样→NRT 对齐）、`/stop`、`/exit`（按 start/zero/none 返回）和
  `/pose`（只读 FK）。断流由 `LeaderInbox` 锁定并关闭 RT 会话；重连不自动 arm。
  目标超过软限位、真机当前超限或步长超限都会在任何运动前拒绝。
- `src/xcore_controller/kinematics.py`：使用 vendor `model().getCartPose()` 对**实际和
  目标关节使用同一模型**生成 pose10；TCP 明确标为法兰（identity toolset），
  没有把法兰静默当作夹爪 TCP。
- `remote-serve --hardware` 与 `xcore-controller-hardware.service` 安装项已加入
  `deploy/install_role_services.py`；该 unit **尚未在远端安装**（部署需要用户确认）。
  本地入口 `start_remote_controller.sh --hardware` 和 `xcore-controller command …` 已实现。
- 离线验证：controller 67 项测试通过，新增映射、解缠、分支、门限、断流停止、
  返回模式和 FK 矩阵测试；Ruff 通过（仅检查本次改动文件，仓库另有历史 E501）。
- 远端只读实测：Python 3.11 环境补装 numpy 2.4.6；copied field calibration to
  `xcore-sdk-python/config/cr7_calib.json`（Git 忽略）。临时启动 `--hardware`
  （约 4 秒，随后停止，未创建 unit）：`motion_capable=true`、`state=idle`、
  `kinematics=vendor_flange_model`、`fk_error=null`；`/pose` 输出合法 pose10，
  与控制器法兰位姿的平移差约 `[-0.11, +0.20, +0.94] mm`。
- **未执行 `/prepare`、`/arm`、`/stop` 的真机运动或退出返回**；真实断流停止、
  对齐运动和 RT 跟随仍需现场人员确认后验收。

### 阶段 3：真实多流 raw 会话与提交协议（代码完成，真机录制未执行）

- `src/xcore_controller/recording.py`：`session/start|stop`、`episode/start|save|discard`。
  独立记录线程按 `recording.raw_fps` 取运动 worker 最新样本，通过 loopback HTTP
  读取两台相机已落盘帧索引，按接收时间选择不晚于样本的最近帧，写入
  `xcore_ee10_rgbd_v1`；`action` 是软限位后的接受目标，`state` 是实测反馈。
- 开始 episode 要求 `armed=true` 且 FK 可用；相机记录目录在 episode 内
  （`episode_XXXXXX/cam1|2`），由相机唯一 pipeline 直接写无损 RGB/Z16。
- 提交复用 xcore-dataset `EpisodeWriter.commit()`：停止相机记录、校验完整、
  清空写队列、fsync 并最后写 `COMMITTED.json`；任何相机失败、丢帧、FK 缺失或
  帧龄超限都会让该片段失败且拒绝 `save`。丢弃保留 `.partial` 和 `DISCARDED.json`。
- xcore-dataset 的 `requires-python` 放宽到 `>=3.11`，使远端 3.11 SDK 运行时可直接
  导入 raw 写入器；转换环境仍为 3.12。远端 3.11 环境补装 Pillow 12.3.0。
- controller 离线测试 71 项通过，新增真实文件＋raw 写入器的双相机提交、
  失败拒绝提交、未 armed 拒绝和 loopback 校验测试。dataset 4 项、adapter 3 项通过。
- 远端冒烟：session 可创建；未 armed 时 `episode/start` 返回 409 并在创建任何
  采集前拒绝；测试 session 已删除。**未执行真机 arm、未录制真实 episode。**

### 阶段 4：会话转换、持久任务队列与拉取（已完成离线／合成验证）

- xcore-dataset 的 `convert` 支持 session 输入：一个 session → 一个 LeRobot 数据集，
  每个封存 episode → 一个 LeRobot episode；特征维度跨 episode 必须一致，
  质量报告逐 episode 记录帧数、最大误差和 `COMMITTED.json` SHA-256。
- 新增 `jobs.py` 与 CLI `queue`／`jobs`／`jobs --run`／`jobs --retry JOB`：
  queued→running→ready/failed；崩溃留在 running 的任务重新排队，staging 改名保留，
  已发布 revision 不覆盖。转换环境需要 FFmpeg 7 的 `LD_LIBRARY_PATH`／`PATH`，
  否则 TorchCodec 加载失败（已实测并写入 README）。
- controller 的 `session/stop` 在 `recording.convert=true` 时后台调用 3.12 dataset
  CLI 排队并执行，不把 LeRobot 依赖加入 3.11 SDK 环境。
- 远端合成两 episode 会话：queue → 首次因 TorchCodec 环境失败 → `--retry` 成功 →
  `READY`/`verify` 通过；远端 `/api/datasets`、`/api/sample` 正常；
  本地 `pull_dataset.sh` 拉取、SHA-256 校验和真实 loader 回读通过（8 帧、2 episodes）。
  该数据明确为合成数据，不是真机采集。

### 阶段 5：本地数采入口、部署与联调（代码完成；真机运动仍未验收）

- 新增 `scripts/start_remote_record.sh`：检查 GELLO／远端角色，启动本地 bridge，
  `--enable-motion` 时先 `prepare` 再 `arm`（均需现场 y 确认），交互键
  R/S/D/P/Q；退出丢弃未保存片段、按 `return_mode` 执行返回并停止 session。
  未加 `--enable-motion` 时只能看状态，不能开始 episode。
- `scripts/start_data_record.sh --remote` 转发到新入口，旧七维流程保持默认。
  新增 `scripts/convert_dataset.sh`（queue／`--retry`／`--list`），经 SSH 在 3.12
  数据环境执行，带 TorchCodec 所需 FFmpeg 环境。
- `setup.sh --check-only` 增加两个数据子项目及 dataset 配置检查。
  `deploy/install_role_services.py` 增加 hardware unit 与 `--add-missing`：
  只补缺失 unit，绝不覆盖已有部署；hardware unit 的 PYTHONPATH 包含
  `xcore-dataset/src`。用户已明确授权安装；2026-10-22 已用远端 3.11 运行时
  （系统 python3 为 3.10，无 tomllib）安装，unit 为 **disabled/inactive**。
  `start_remote_controller.sh --hardware` 实测可启动 unit 和隧道，状态为
  `motion_capable=true`、`idle`、`vendor_flange_model`、无 FK 错误、
  `conversion enabled=true`；测试后已停止 tunnel／unit，端口释放。
- xcore-adapters 新增 `AttachedLeader`／`AttachedRobot`：只附着 loopback 上已运行的
  worker，只读状态／样本，不导入 LeRobot／SDK、不启动硬件、不发运动命令。
- 联调（无运动）：本地 GELLO 服务＋远端临时 `--hardware`（4 秒后停止）＋SSH 隧道，
  `start_remote_record.sh` 成功创建 session、未授权运动提示、退出后 session 关闭、
  bridge 清理、端口释放；测试 session 已删除。真机 arm／episode 采集未执行。
- 验证：controller 71 项、adapter 5 项、dataset 6 项测试通过；新脚本 shell 语法、
  `--help`、`convert_dataset.sh --list` 实测通过。

### 修复：长时运动命令的 HTTP 客户端超时（2026-10-22 实机）

- 现场启动跟随时报错：`prepare` 在远端执行 NRT 对齐，客户端 `urlopen` 固定 2 s
  超时先返回 Traceback，脚本中止；**远端仍继续完成对齐**，机器人实际移动到了
  对齐姿态（实测 J≈[175.6, 3.8, 6.8, 5.9, 5.0, 3.3]°），但未执行 `arm`，
  运动中状态为 idle/unarmed，没有遗留跟随会话。
- 修复：CLI 按动作设置超时（`prepare`／`exit`／`return` 900 s，`arm` 60 s，
  `episode/save` 600 s 等），超时错误提示“远端可能仍在执行，先查 status”；
  数采脚本在 prepare 前打印等待提示，不再让操作者误以为卡住或失败。
- 运维规则：任何客户端超时都不能当作远端已取消；先查 `/status` 和实测位姿，
  不要立即重复发送运动命令。若已对齐，下一次 prepare 会在容差内直接跳过。

### 修复：arm 后 1 秒内断流误停（2026-10-22 实机）

- 现象：脚本显示“会话已创建”，但机械臂不跟随；`/status` 为
  `state=stopped`、`armed=false`、`forwarded=5`，原因
  `leader stream failure: leader stream stale; explicit re-arm required`。
- 诊断：远端已成功进入 RT（日志显示 ①～⑪ 全部完成、真实跟随启动），但主臂样本经
  本地 HTTP bridge 跨 SSH 到达；RT 回调 1 kHz＋25 Hz 伺服线程运行后约 1 秒内没有
  `/leader` 被接收，`LeaderInbox` 的 1.0 s 超时把跟随停掉。机器人只保持最后目标，
  没有失控运动。旧客户端 2 s 超时和中断的 bridge 会放大该问题。
- 修复：controller 新增 `[robot].remote_stale_timeout_s`，默认 **3.0 s**
  （范围 0.5..10）；远端 hardware 角色设置 `sys.setswitchinterval(0.0005)`
  降低 RT 线程对 HTTP 线程的 GIL 饥饿；bridge POST 超时放宽到 5 s；
  `/status` 增加 `leader_age_s`，停止原因记录实际断流秒数。
- 验证：离线 72 项测试通过，远端 unit 已重启加载新配置。**仍需现场重新 arm 验证**；
  若再次停止，先看 `leader_age_s` 和日志中的实际断流秒数，不要立即重复发 arm。

- 第二次现场 arm 仍停止，日志给出 `after 0.51s without a sample (timeout 3.0s)`：
  真正生效的是 **`LeaderInbox` 的 0.5 s 超时**（`[roles].leader_timeout_s`），
  而不是运动 worker 的 3 s。hardware 模式现改为
  `max(roles.leader_timeout_s, robot.remote_stale_timeout_s)`，让 inbox 与 RT
  看门狗使用同一个 3 s 阈值；只读角色仍保留 0.5 s 的快速状态标记。
- 远端 unit 已重启；仍需现场重新 arm 验证实际跟随。

### 修复：退出返回 409（2026-10-22 实机）

- 现象：按 Q／退出时打印“退出返回（模式 zero）：真实运动”，随后
  `urllib.error.HTTPError: HTTP Error 409: Conflict`；机器人未移动。
- 原因定位困难：CLI 的 `request()` 未读取 HTTP 错误体，服务端也未记录 409 内容。
  已改为 CLI 抛出 `HTTP x: {body}`，服务端把每个失败命令写进 journal。
- 最可能的直接原因：`exit` 在 `disarm()` 关闭 RT 后立刻调用 NRT `movej`，
  而 `RobotDriver.movej` 要求 `operationState == idle`；RT 收尾尚未完成时会被拒绝。
  现在返回前等待 idle（最多 8 s），超时会明确报出当前 operationState；
  prepare／return 的 `finally` 不再用清理异常覆盖原始错误。
- 离线测试：新增“RT 收尾非 idle 时等待后再返回”用例，controller 73 项通过。
  远端 unit 已重启；退出返回仍需现场确认后重试（zero 模式会让 J1 从约 175° 转回 0°，
  执行前必须确认该路径安全）。

### 未解决：退出返回因控制器掉电失败（2026-10-22 实机，暂不处理）

- 用户按 `exit --return-mode zero`，客户端已能显示完整错误体：
  `HTTP 409: {"error": "XCoreError: Motion stopped by controller: power state off;
  read controller-logs for the fault code"}`。
- 解释：返回流程已通过 idle 等待和参数检查，但在 `movej` 执行期间控制器报告
  `power state off`，`RobotDriver.movej` 按设计中止并抛出。说明 CR7 当前处于
  下电／掉电（可能是示教器下电、急停或控制器保护），不是本次 409 的 idle 时序问题。
- 当前状态：机械臂未完成返回，停在约 `[175.8, 2.7, 4.8, 3.2, -1.5, 3.2]°`；
  **尚未确认上电与急停状态，也未读取 controller logs**。经用户要求，本轮不继续修复。
- 下次处理顺序：先在示教器/HMI 确认无急停并上电 → 读取 `xcore controller-logs`
  → 确认 `operationState=idle`、`powerState=on` → 再重试返回。不得用反复 arm／movej
  掩盖掉电或保护状态，也不要在未确认安全路径时执行 zero 返回。

### Q 退出返回：模式排序修复（2026-10-26，真机返回待验证）

- 已重连远端 `rokae@192.168.2.225`，只读查询 CR7：manual/off/idle，
  J≈`[175.77, 0.22, -0.30, 3.64, -1.61, 3.22]°`，没有运动或上电。
  控制器最新 10 条错误均为 10-22 17:58 左右的 50115 奇异点；不是 21:22 的
  同时段故障证据，不能由这些历史条目推断 Q 掉电原因。
- SDK 日志显示 21:22:16.162 上电后，16.165 又设置 NRT，16.248 moveStart，
  随后立即检测到 off。厂商 `example/setloop.py`／`move_command.py` 对 RT→NRT
  的注释明确提到下电。这支持模式切换顺序的疑点，但尚未通过真机重现确认唯一根因。
- 修复 controller prepare／return：先设置 NRT，再 automatic／power on；
  `movej(..., motion_mode_prepared=True)` 跳过第二次模式切换，排队前复查上电。
  默认 SDK 调用保留模式设置，但如随后已下电则在 moveReset 前拒绝，不隐式重新上电。
- 故障清理 `_restore` 不再在返回失败后恢复 prior power=on；Q 清理失败显式输出提示
  并返回非零退出码，仍清理 bridge／session，不把失败伪装成正常完成。
- controller 74 项、SDK 驱动／跟随／准备／返回相关 83 项回归通过。
  数据工具另修复 Python 3.11 支持与无条件 3.12 extras 的冲突：LeRobot、Torch、
  LeLab 及 uv override 增加版本条件，3.12 dataset/app 六项测试通过。
- **Q 的真机返回尚未验收**。后续现场按既有入口确认路径后测试；若仍报错，保留
  同时段 journal／SDK 日志和最新控制器日志，不自动重试返回或上电。
- 上述三个运行文件已同步到远端并核对 SHA-256，远端导入／shell 语法检查通过；
  原文件备份为 `~/.local/state/xcore-q-fix-20261026.P8UhnK/`。
  hardware／readonly／simulate unit 均保持 inactive；本轮未启动跟随或执行 Q 返回。
  独立 Python 3.11 环境导入 raw writer 通过，uv lock 检查通过。修改尚未 commit／push。

### R/S 保存断流及新链路夹爪缺失修复（2026-10-26）

- 现场：session_20261026_095352 的 episode_000000 保存返回 `committed=true`、466 行，
  但本地 bridge 的 `/leader` 超过 5 秒无应答，远端 3 秒看门狗停止跟随。
  根因：`RemoteSession.call("leader")` 在接收后调用全量 `status()`，间接等待
  `SessionRecorder.save_episode()` 持有的状态锁；保存还在同一状态锁内 join 记录线程，
  而记录线程更新行数／错误也需要该锁。
- 修复：handshake／leader 只返回 accepted／sequence，不查询 recorder 或 converter；
  录制生命周期操作使用独立 operation lock，状态锁仅保护短状态更新，不跨 camera I/O、
  commit 或 join。状态可在保存期间显示 saving；无新机器人样本时将片段判为失败。
- 新远端数采链路原本没有夹爪 follower，state/action 的 closure 硬编码为 0，
  README 也遗漏夹爪启动。新增 `gripper.py` 复用 SDK 的 TCP GripperFollower：
  远端 loopback 接入现有独立服务，arm 前只读检查激活，arm 后由独立线程下发目标，
  SDK 线程仅提交最新值和读取缓存；disarm／断流／错误／退出时停止夹爪。
  ID7 使用 SDK `[gripper]` 的角度／位置／速度／力配置，默认 `robot.follow_gripper=true`。
  state[-1] 写实测 closure，action[-1] 写扳机期望，额外记录 raw 位置及反馈时间；
  反馈过期／错误会停止跟随。显式禁用时元数据保留说明，不伪装实测。
- 远端夹爪 unit 原为 inactive，已启动其 `--no-activate` API；只读检查确认夹爪尚未激活，
  本轮未发送 activate、set_target 或开合。用户须确认空间后执行 README 中的
  `uv run --project xcore-gripper-2F85 gripper activate --host 192.168.2.225 --port 5005`，
  再开启数采。入口在 prepare 前检查夹爪，不会只动六轴却忽略夹爪未就绪。
- 用户确认已退出原会话后再次检查 session=null、armed=false，备份至
  `~/.local/state/xcore-record-fix-20261026.ARX6ie/`，部署并重启 hardware API；
  最终 idle／armed=false、gripper_enabled=true，未自动恢复跟随或执行返回。
  夹爪 API active、disabled；未改变开机自启策略。
- 另发现 Q 后后台转换因 cwd `~/project/xcore-controller/xcore-dataset` 不存在而失败。
  远端是源码快照、两新项目在同级，已补两个缺失符号链接指向 `../xcore-dataset` 和
  `../xcore-adapters`，没有替换现有源码或数据；转换 CLI 入口验证可用。
  这不代表原真实会话已转换发布，需另查转换任务状态。
- 原 466 行片段的 COMMITTED.json／1878 个文件校验通过，保留不覆盖；其夹爪数据
  为旧版本明确标记的零占位，无法事后补回实测。用户后续应新录制含夹爪反馈的片段。
- controller 81 项回归通过，包括慢保存时连续接收主臂数据、保存期间状态可读、
  夹爪 TCP follower 模拟、实测／目标分离、未激活拒绝起臂和停臂时停夹爪；
  改动 Ruff、shell 语法通过。真实夹爪跟随与修复后的 R/S 仍待现场验证。
  README／配置参考／CHANGELOG 已同步；当前修改未 commit／push。

### 跟随启动时序、RT 收尾与真实小幅验收（2026-10-26，最新）

- 用户实测六轴／夹爪均不跟随，终端无错误。日志确认上轮新接入的夹爪初始反馈
  在 RT 初始化期间超过 0.75 s；两端一起停止。重复运行还出现
  `Attempted to start multiple motions`。旧 `/arm` 在实际 RT 初始化前便返回成功，
  shell 没有持续监测远端停止原因，形成假成功。前述“81 项通过”没有覆盖该硬件时序。
- GripperFollower 增加可选 `poll_when_idle`，新远端链路在无目标时只读刷新反馈，
  不发送 set_target。MotionWorker 的 arm 进入 arming、保持实测关节姿态，等待
  RT active、至少 3 次回调和新鲜夹爪反馈，再复查主臂门限并返回 armed=true。
  默认超时 20 s（robot.arm_timeout_s，1..30）；预热只容忍反馈暂未刷新，运行中
  的过期／网络故障仍严格停止。stop 可取消正在预热的 arm。
- SDK 公开 startLoop docstring 明确说明：`startLoop(False)` 需要 stopLoop，
  否则无法开始下一周期。去除已废弃且重复启动 loop 的零距离 RT MoveJ；
  在最终回调 setFinished 结束后 stopLoop，再 stopMove；close 检查伺服线程结束，
  清理失败会锁住后续 prepare／arm／return，不能静默复用残留 RT 对象。
  远端 bot 使用 CheckedRobot 检查厂商错误码，与旧直接跟随链一致。
- 新 `watch-motion` 及脚本后台健康监测每秒 2 次检查远端（roles.status_poll_hz），
  无需再按键即显示故障并退出；故障时 stop／丢弃未保存片段／关闭 session，
  不自动返回。正常 Q 的返回模式不变。空 session 不提交转换。
- 同时修复转换 ABI 污染：SDK unit 的 PYTHONPATH 指向 vendor311，原 3.12 转换
  子进程继承后加载 3.11 NumPy 而失败。ConversionScheduler 复制并去掉 PYTHONPATH／
  PYTHONHOME，保留 FFmpeg 环境。远端已实测导入 dataset-venv 自己的 NumPy 和
  TorchCodec；未把原失败空会话伪报为已转换。
- 用户明确确认现场安全，授权当前姿态零位移 RT 启停两次及夹爪小幅开合。
  使用临时 `/tmp/xcore-follow-acceptance.py`，映射固定为刚读到的实测关节值，
  仅测试此临时进程，不修改现场标定；未执行 prepare／return／回零。
  同一个 SDK 会话连续两轮成功 arm（约 0.84／0.83 s），转发 254／50 次，
  两次均明确 stopLoop／stopMove 并正常结束，无 cleanup_fault。
  最大实测关节漂移约 0.00133°。
- 夹爪目标从当前位置增加约 10 raw 再返回，记录到实测 closure 约 0.00784～0.05490、
  目标约 0.01134～0.05129，确认真实响应。第一轮同时通过 HTTP R/S 录制双 RGBD，
  31 行已封存，保存期间 forwarded 持续推进、publisher_errors=[]。
  原始数据在 `~/project/xcore-data/raw/validation-stationary-20261026/` 下的
  `session_20261026_103712/episodes/episode_000000`，任务标记 VALIDATION ONLY，
  主臂输入为测试固定值，不是训练示范；本轮未转换／发布这段验收数据。
- controller 88 项、SDK 全量 225 项离线回归通过；包含终端无按键仍发现后台故障、
  故障不回零、夹爪反馈预热、异步 arm 错误、RT 调度收尾与 ABI 隔离。
  常规 API 已恢复为 idle／armed=false、gripper_enabled=true、cleanup_fault=null；
  现有 GELLO 与 SSH 隧道保留，未自动进入真实 GELLO 轨迹跟随。
  此验收覆盖启动／保持／夹爪小幅动作／R/S／重复启停，不代替六轴大范围轨迹验收。
  修改仍未 commit／push。

### 一条命令准备数采环境（2026-10-26，最新入口）

- `scripts/start_remote_record.sh --task "…" --enable-motion` 默认自动启动并验证：
  远端 hardware API／SSH 连接、夹爪 API、本地 GELLO 七通道、双 RGBD 和 LeLab。
  新增 `session_setup.py`／`xcore-controller setup-session` 复用已有相机启动器、
  role launcher 与夹爪 TCP 协议。有效服务可复用；活动跟随／会话、错误角色、
  未完成 RT 清理、FK 不可用、主臂帧过期及相机录制配置缺失均在运动前拒绝。
- 准备阶段只读检查夹爪；一次 `y` 现场确认后才按需激活，已激活时不重复初始化。
  单纯旧断流锁在确认且 controller 未 armed／无活动会话后以 stop 清除，其他故障拒绝。
  默认自动创建缺失的本地 controller uv 3.11 环境，但不编造现场标定、SSH 登录凭据
  或自动替换远端部署。这里的“从零”指已有部署下所有日常服务停止的状态。
- 新 `--check-only` 启动并检查服务后退出，无激活／prepare／arm；
  `--no-auto-start` 保留手动调试。日志为 `logs/remote-record-*`，相机完整启动输出写
  cam1／cam2-startup.log，终端显示阶段及网址。`timeouts.startup_ready_s` 默认 30 s。
- 增加单数采入口锁，启动的本地 GELLO／controller 与 LeLab 连接属于独立进程组，
  失败／取消／退出时清理自建进程，预存本地服务保留。远端 API 按需保持运行，以便
  会话退出后后台转换；相机连接复用既有 SSH control socket。没有启用开机自启。
- 现场确认无活动会话、夹爪静止后，停止旧 GELLO、旧 controller 隧道，以及所有
  controller／夹爪／相机／dataset 远端服务，然后执行一条 `--check-only`：
  五阶段均通过，真实七通道反馈、两路新鲜 RGBD、夹爪状态、LeLab 列表均可用。
  再次执行检查也通过，复用了远端服务；未上电、未激活、未对齐或进入跟随。
- 新增冷启动、服务复用、取消不动作、单次确认顺序、错误服务／忙会话／陈旧输入拒绝
  和激活幂等性测试；controller 当前 99 项通过。README 已以单命令作为日常入口，
  分步流程保留为手动调试。修改未 commit／push。

### S 保存看似无响应与按键积压（2026-10-26）

- 用户 session_20261026_111111/episode_000000 返回 rows=420、committed=true，
  COMMITTED.json 实际存在；远端 recording 无错误，跟随未因 S 中断。此处未验证
  LeRobot 转换成品，不以 scheduler 的 ready 字段替代数据成品校验。
- S 同步等待图像落盘／校验／封存，原入口没有保存中提示；忙时输入的重复 S/D
  在保存完成后被逐个消费，因片段已经关闭而显示“没有活动 episode”。该提示只在
  S/D 分支出现，不能把它解释为 R 请求保存，或把延迟输出当作片段丢失。
- 入口新增保存中／完成提示，交互阶段持续 noncanonical／noecho（保留 Ctrl+C，
  关闭 Ctrl+S 流控），退出先恢复 stty。保存／丢弃后收集忙时积压键，忽略 S/D，
  R 保留一次作为下一段开始请求，Q 优先作为保存后退出。非 TTY 的脚本输入仍按原顺序处理。
- 已用真实 PTY 验证不需回车的 R/S、慢保存即时提示、积压 ssdr 后只再次 start 一次、
  无“没有活动 episode”刷屏，以及 Q 后 termios 完整恢复。只修改本地／远端脚本，
  无须重启控制服务，未进行额外机械臂运动；修改未 commit／push。

## 已发布基线与下一步优化（2026-10-26）

用户要求先将当前代码全部 commit／push，再把以下两项优化作为待办记录，
单独 commit／push。本轮只记录计划，不开始开发网页或新的拉取模式。

第一轮已推送到各仓库 main：controller `5dddab2`、SDK `27dfe8a`、
dataset `943119e`。父仓库已更新两个 submodule 指针；其余子模块未改变。
上文各历史检查点中的“未 commit／push”是当时状态，至本基线均已发布。
已验证 controller 100 项、SDK 225 项、dataset 6 项测试；硬件验收边界仍以
前述当前姿态保持／夹爪小幅动作／R/S 记录说明为准，不扩大为任意轨迹验收。

### 待办一：参考 AgileX 增加统一网页控制与数采面板

当前只有两个相机预览页、只读 LeLab 浏览，以及 controller 的 HTTP 命令；
**尚无统一网页数采控制面板**。参考相邻
`../../agilex/agilex-controller/src/agilex_data_collection/` 的页面交互、会话状态机、
后台任务及测试思路；CR7 驱动和 RT 控制继续使用本项目已有实现。

目标与分工：

- 在 xcore-controller 增加本地网页入口，复用一键环境准备、GELLO、数据桥与远端 API。
  本地仍负责操作界面和主臂输入；远端继续独占 SDK／夹爪／相机、记录、转换和数据存储。
  网页操作不能再打开第二个 SDK 连接、GELLO 串口或相机 pipeline。
- 同一页面填写任务、确认运动范围、启动／停止跟随；提供开始记录、保存、丢弃、
  结束会话按钮，对应已有 R/S/D/Q。显示实际阶段、保存中／已保存、行数、片段数、
  关节与夹爪反馈、错误原因和转换进度，集成两台相机各自 RGB＋深度预览与 LeLab 入口。
- 长时 prepare／arm／save 在后台执行，页面保持响应；按钮按状态禁用并拒绝重复请求。
  成功依据远端真实状态，不能把 HTTP 请求已发送或返回 200 当作已跟随／已保存。
  超时或断线后先查询任务／远端状态，不自动重放运动或保存命令。
- 页面确认与后端检查同时保留，前端勾选不是唯一的运动校验；CLI 和网页使用同一
  会话互斥机制，拒绝同时操作同一硬件。正常结束按 return_mode，故障沿用 stop、
  不自动返回的策略；不能借网页迁移改变现有退出与保护行为。
- 网页刷新／关闭不自动重新 arm、保存或丢弃；关闭页面不等同于停止硬件，需明确
  使用停止跟随／结束会话。只监听本地 loopback，经既有 SSH 连接远端，同源校验保留。
  预览复用已有帧缓存，编码／网页和写盘不进入 RT 回调。
- 初版 LeLab 继续只读浏览；AgileX 的合并、上传、删除等功能不属于此次网页目标，
  不因复用页面而开放上游训练、校准、运动或外部上传接口。

拟在现有 `start_remote_record.sh` 增加网页模式（例如 `--web`，**尚未实现**），
保持一个启动入口。先模拟验证状态切换、重复点击、长时保存、错误展示、刷新／关闭
及与 CLI 互斥，再做浏览器界面验收；新增实际运动验证需当次现场确认。

### 待办二：为数据拉取增加 --pose／--joints 两个常用参数

当前 `scripts/pull_dataset.sh DATASET_ID REVISION` 两个位置参数分别选择数据集
和发布版本，**不是末端／关节类型**。当前只拉完整 EE10 LeRobot 发布包；关节反馈
和目标在 raw 的 samples.jsonl 中，已有 LeRobot 特征没有保留完整的关节状态／动作。
`--pose`、`--joints` 均尚未实现，不要把下列拟定命令当作当前可用命令。

```bash
# 拟定：明确选择末端表示或关节表示，ID／版本仍说明拉哪份数据。
./scripts/pull_dataset.sh --pose DATASET_ID REVISION
./scripts/pull_dataset.sh --joints DATASET_ID REVISION
```

- 两选项互斥；保留旧 `DATASET_ID REVISION` 命令的完整 EE10 包拉取行为。
  新帮助文档须明确三件事：表示类型、数据集／会话标识、版本；可增加只读 `--list`
  显示已发布数据及支持的表示，避免要求用户猜测 ID／版本。不能静默选择未完成任务。
- `--pose` 选择 pose10：xyz（m）＋旋转矩阵前两列按列拼接＋夹爪闭合度，
  分别提供实测 state 和接受的目标 action。沿用已有模型／坐标系和法兰 TCP 标注，
  不把尚未验证的夹爪 TCP 宣称为真实工具标定结果。
- `--joints` 选择记录到的六轴关节角（rad）、关节目标、夹爪及原始时间戳，保留
  请求目标／接受目标的来源区别。如提供 LeRobot 关节表示，state/action 明确为
  `[q1,q2,q3,q4,q5,q6,g]` 七维并独立声明 schema；原始关节审计数据保留原语义。
  必须从原 raw 的 joints_rad／requested_target_rad／target_rad／closure 等字段
  构建，不能对 pose10 做 IK 反推关节，也不能把末端成品重命名成关节格式。
- 上述两模式选择运动学表示；默认仍保留两台相机各自 RGBD、12 维力及有效掩码、
  任务字符串和时间／标定信息。“仅末端”不应被静默解释为丢掉图像、深度或力字段；
  将来若需要纯位姿小表格，可另设明确选项，不能改变已确认的数据契约。
- 关节表示的导出／转换继续在远端完成：xcore-adapters 负责字段／特征适配，
  xcore-dataset 负责从封存 raw 生成、验证和不可变发布；controller 只选择表示、
  SSH／rsync 拉取并验证。不修改其他项目共享的 lerobot-converter。
- 发布清单／索引应明确 representation、源 session／episode、源校验和及 schema，
  能从自定义 dataset_id 追溯 raw，不假设 dataset_id 必然等于 raw 目录名。
  缺少关节字段的旧数据明确拒绝该模式，不以零占位伪造实测。
- 两种表示使用可区分的远端发布与本地落盘位置，不能同 ID／版本互相覆盖；
  重复拉取的 already_present 判断也必须核实表示类型。保留断点续传、SHA-256、
  真实 loader 回读、partial→完成目录发布和远端源数据不删除的行为。
- 验收覆盖模式互斥／非法参数在 SSH 前拒绝、旧命令兼容、双表示维度与单位、
  RGBD／力／任务完整性、来源追溯、缺字段拒绝、错误数据拒绝、断点续传和重复拉取。
  完成后同步 README／CLI 帮助／配置及测试，再更新子仓库和父仓库指针。

## 优化落地检查点（2026-10-26）

用户要求实现“网页控制”和“数据传输参数”两个方案。两项均已实现并通过离线测试与
只读远端联调；**未执行网页 arm、真实关节数据转换或任何新增运动**。

### 一、统一网页控制与数采面板（已实现，浏览器交互待人工验收）

- 新增 `src/xcore_controller/web.py` 与 `xcore-controller web`，由
  `start_remote_record.sh --web [--enable-motion]` 启动，默认
  `http://127.0.0.1:8095`，只监听 loopback。页面复用现有 GELLO／bridge／远端 API，
  不打开第二个 SDK 会话、串口或相机 pipeline；预览直接使用两台相机已转发的 MJPEG。
- 页面操作：填写任务、启动跟随（可选夹爪激活→prepare→arm→session/start）、停止跟随、
  开始记录、保存、丢弃、结束会话（按 `return_mode`）。显示运动/夹爪/记录/转换状态、
  行数、片段、错误和两路 RGB/深度预览，提供 LeLab 链接。
- 所有长操作进入单一后台 job，页面轮询真实远端状态；job 运行期间拒绝重复请求。
  成功以远端 armed/committed 状态为准，不把 HTTP 200 当作成功。保存/丢弃按钮按
  episode 状态禁用；结束会话要求先保存或丢弃。
- 运动安全：`--web` 不加 `--enable-motion` 为只读（只能看状态和预览）。start／finish
  需要前端勾选 + 服务端一次性确认令牌（`[web].confirmation_ttl_s`，默认 90 秒）；
  start 还检查远端未 armed、无活动 session、无 cleanup/fk 错误、GELLO 样本新鲜、
  两台相机 streaming 且帧龄正常。夹爪激活由 web job 通过既有 session_setup 执行。
- 刷新页面会在心跳宽限内重新连接并取消关闭；关闭页面/浏览器崩溃经过宽限后执行
  **完全关闭**（丢弃未保存片段、停止会话、按 return_mode 返回、下电、停服务）。
  这是 2026-10-26 用户后续明确要求，取代早期“关闭页面不影响硬件”的设想。
  网页与 CLI 共用 `logs/.remote-record.lock` 和远端会话互斥。
- 实测（无运动）：本地 GELLO 服务＋既有远端 hardware 角色＋临时 SSH 隧道，
  `start_remote_record.sh --no-auto-start --web` 成功启动面板；`/api/state` 显示
  `motion=idle`、`allow_motion=false`、两台相机 streaming；只读 start 被 409 拒绝，
  跨源 POST 被 403；退出启动器后 web/bridge 均清理，端口释放。带 `--enable-motion`
  的页面点击与真实 arm 尚未验收。
- 新增 `[web]` 配置与 `XCORE_WEB_*` 覆盖；`docs/reference/{cli,config}.md`、README、
  测试同步。浏览器排版和按钮点击仍需人工验收。

### 二、拉取 pose／joints 表示（已实现，合成数据验收）

- xcore-adapters 新增 `JOINT_NAMES`／`validate_joint_state`：`[q1..q6, closure]`，
  rad 与 0..1 闭合度。xcore-dataset 的 `convert` 增加 `representation`：
  - pose10：保持原 10 维；
  - joints：state=`joints_rad`＋`closure`，action=`target_rad`＋`target_closure`；
    缺失字段明确拒绝，**不对 pose10 做 IK**，也不替换成下一帧实测。
- 发布目录新增 `representation.json`（schema、名称、单位、action 语义、TCP、来源
  session／episode、源 COMMITTED SHA-256、dataset_id／revision），并进入 READY 清单；
  质量报告记录 representation。joints job 默认 dataset_id 为 `<session>-joints`，
  与 pose10 目录分开；job 记录 representation，旧 job 缺省按 pose10。
- 新增 `datasets --root` 只读列表；旧数据集无标记时按 observation.state 维度推断。
- `pull_dataset.sh` 支持 `--pose`／`--joints`（互斥）和 `--list`；旧
  `ID REVISION` 保持 pose10 完整包行为。拉取后先校验 representation，匹配后才
  partial→正式目录；已存在版本也会检查表示，避免同 ID 互相覆盖。
- 远端合成会话实测：`queue --representation joints` → job ready →
  `datasets` 显示 `joints-check-20261026-joints/rev-0001` 为 joints；本地
  `pull --joints` 校验 SHA-256 与 loader 回读通过（4 帧、7 维）；对同一版本执行
  `--pose` 被 representation mismatch 拒绝并保留 partial。
- 现场两条旧真实会话的转换任务此前因 `conflicting image metadata at same
  timestamp` 失败，本次未处理，也不代表关节表示已用真实数据验收。真实关节数据集
  需重新录制后用 `queue --representation joints` 生成。
- 测试：controller 109 项、adapter 6 项、dataset 9 项通过；Ruff、脚本语法和
  `pull --list`／远端转换实测通过。

### 网页面板布局优化（2026-10-26，用户反馈后）

- 用户反馈“画面很差、无法最大化、布局不行”。重做页面布局：加入 viewport、
  全高 flex/grid 三栏（顶部状态栏＋左侧控制/状态＋右侧 2×2 预览），
  所有网格子项 `min-height:0`，图片以 `object-fit:contain` 填满各自画面；
  窄屏自动改为上下布局，不再被固定 360px 侧栏挤住。
- 新增“全屏”按钮（`requestFullscreen`）和每个相机画面的单独全屏；“最大化预览”
  隐藏控制栏，让四路 RGB/深度画面占满窗口。预览图片只在 URL 变化时重设 `src`，
  不再每 500ms 重建 MJPEG 连接（旧实现会反复打断画面）；断流时显示提示并每 2 秒重试。
- 状态由原始 JSON 改为指标卡片（运动/主臂帧龄/转发/夹爪/会话/片段/行数/记录/转换），
  错误集中显示，原始 JSON 放在可展开区域；job 步骤和失败原因在左侧显示。
- 页面按钮状态、后端检查、确认令牌和断电保护逻辑未改变。控制台已用无头 Firefox
  尝试截图但环境未产出文件（MJPEG 持续加载可能阻塞截图），页面 HTML/JS 语法
  `node --check` 通过；**实际排版与全屏按钮仍需用户在浏览器验收**。

### 修复：真实会话未出现在 LeLab（2026-10-26）

- 用户看到 LeLab 只有三个合成版本，怀疑读的是本地数据。核实：面板链接到
  `127.0.0.1:8090` SSH 隧道，远端 dataset unit 的 `--root` 为
  `/home/rokae/project/xcore-data/lerobot`；LeLab `/datasets` 与远端目录一致，
  **确实是远端数据**。缺少的是刚保存的 session，因为转换 job 失败。
- 两个转换缺陷：
  1. 多个机器人样本引用同一相机帧时，`uncertainty_ns`（记录时帧龄）随样本不同；
     旧代码把整个 image dict 当身份比较，误报 `conflicting image metadata at same
     timestamp`。现在只比较 path／帧号／时间等身份字段，帧龄取保守最大值。
  2. 转换把记录时帧龄当作时钟误差加到匹配误差里，导致 50ms 容差拒绝了实际最近帧
     仅 33–68ms 的真实片段。现在只用 `abs(frame_time-target)+clock_uncertainty_ns`；
     帧龄写入 `quality_report.max_recorded_frame_age_ms`。新录制行写
     `clock_uncertainty_ns=0`、`uncertainty_ns=0`、`age_ns=<采样帧龄>`。
- dataset `max_skew_ms` 默认从 50 改为 **100ms**：15fps 双相机偶发丢帧时最近帧
  可达约 68ms；质量报告仍记录逐流真实误差，不能把 100ms 当作硬同步。
- 重跑三个失败 job（旧 job 的 50ms 容差同步更新为 100）：
  `session_20261026_123845`（117 帧、1 episode，用户刚保存的数据）、
  `session_20261026_111111`（280 帧）、`session_20261026_112434`（414 帧、2 episodes）
  全部 READY；远端 LeLab `/datasets` 已列出，`/api/sample` 可读回真实 pose10、
  task 和 640×480 深度。未改动机器人、相机或夹爪状态。
- 验证：dataset 10 项、controller recording 6 项通过；无新增运动。

### LeLab 删除按钮与网页面板按钮检查（2026-10-26）

- “delete failed” 原因：`app.py` 的只读中间件只放行 `POST /dataset-info`，
  LeLab 的 `POST /delete-dataset` 被 403 拒绝；服务本身没有删除路由。
- 新增受控删除 `xcore_dataset/maintenance.py` 与 `POST /delete-dataset`：
  只允许 `<published_root>/<dataset_id>/rev-NNNN/` 且存在 `READY.json`；
  拒绝路径穿越、绝对路径、symlink、raw/staging/jobs 和 `delete_from_hub=true`。
  `[server].allow_delete` 控制开放（当前远端为 true），删除不可恢复但不触碰 raw。
  新增 CLI `delete DATASET REVISION --root … --yes`。
- 远端 dataset 服务已重启加载新代码；用临时 revision 验证 HTTP 删除成功，
  随后按用户意图删除了三个测试版本：
  `e2e-check-20261022`、`joints-check-20261026-joints`、`synthetic-check-20261022`。
  远端 LeLab `/datasets` 现仅剩下真实会话（含新发布的
  `session_20261026_130329/rev-0001`）；对应 raw 数据保留，未删除。
- 网页面板按钮核对：启动（gripper→prepare→arm→session）、停止、开始记录、保存、
  丢弃、结束会话、最大化预览、整页/单画面全屏均有对应动作；新增 record-discard
  与 finish 无 episode 的测试，修正主臂帧龄显示（原 JS 从 motion 里取，实际在
  remote 顶层，现改为 `S.remote.leader_age_s`）。真实 arm 相关按钮仍需现场确认后
  验收；只读/HTTP 层与离线状态机测试通过。
- 验证：dataset 19 项（含 9 项删除测试）、controller 109 项、web 8 项通过。

### 完整生命周期：一条命令激活并关闭所有远端部件（2026-10-26）

- 用户要求：远端全部停止时，执行一条数采命令即激活夹爪与机械臂并开始数采；
  Q／Ctrl+C／关闭网页时自动关闭所有已激活部件。
- `--enable-motion` 在终端模式仍先有一次 `y` 确认，然后激活夹爪、prepare、arm、
  session/start；`--web --enable-motion` 现在也会在打开页面前完成同一套激活和会话创建
  （页面直接进入可记录状态），不再要求先点页面“启动跟随”。
- 新增远端 `/shutdown`：丢弃活动 episode（未封存）、停止会话并排队转换、
  disarm、按 `return_mode` 返回、机械臂 manual＋下电；返回或下电失败会分别报告。
  故障退出使用 `shutdown --return-mode none`：停止并下电，但不自动返回。
- 脚本退出统一调用 `/shutdown`，然后停止本次启动的远端 hardware／相机／
  dataset／夹爪 unit；`--keep-services` 保留服务，`--check-only` 不停止。
  停止服务前会等待后台转换结束（`timeouts.conversion_wait_s`，默认 600s）；
  超时则保留 controller/dataset 以免中断转换。
- 网页新增心跳与关闭检测：每 2 秒 `POST /api/heartbeat`；`pagehide` 用
  `sendBeacon('/api/leave')`；`[web].close_grace_s`（8s）后执行完全关闭。
  刷新页面若在宽限内恢复心跳则取消；浏览器崩溃由 `heartbeat_timeout_s`（120s）兜底。
  关闭网页现在会下电并停止远端服务，这与早期“关闭页面不影响硬件”的约定不同，
  是用户本轮明确要求；`--keep-services` 可在调试时保留服务。
- 离线验证：controller 113 项通过，新增 shutdown 返回/下电、心跳/leave、
  shutdown 会话转换排队、shell 故障 shutdown 和生命周期测试；JS/Ruff/脚本语法通过。
  **真机上的返回、下电、关闭网页和停服务尚未验收**，首次现场测试需确认急停可达、
  返回路径安全、下电后抱闸保持正常；不要把离线通过当作硬件验收。
