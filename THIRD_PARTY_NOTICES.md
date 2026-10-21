# 第三方组件说明

本仓库通过 submodule 和 Python 依赖使用以下第三方组件。各组件的完整许可证
以其仓库或发行包中的 LICENSE 文件为准。

| 组件 | 用途 | 许可 |
| --- | --- | --- |
| GELLO（`xcore-gello-software`） | 主臂读取、标定与上游实验代码 | MIT |
| ROKAE xCore SDK | CR7 厂商二进制扩展 | 厂商许可，随 SDK 分发 |
| Robotiq 2F-85 手册与驱动参考 | 夹爪协议与寄存器说明 | Robotiq 文档许可 |
| pyrealsense2 / librealsense | Intel RealSense 采集 | Apache-2.0 |
| LeRobot | 数据集格式与写入 | Apache-2.0 |
| NumPy | 数值计算 | BSD-3-Clause |
| Pillow | 预览 JPEG 编码（远端） | HPND（PIL 许可） |
| pyzmq | 本机 RPC | BSD-3-Clause |
| pyserial | RS485 串口 | BSD-3-Clause |
| dynamixel-sdk | GELLO 舵机通信 | Apache-2.0 |
| Tyro | GELLO 只读 CLI | MIT |

`xcore-sdk-python/Release/` 中的厂商扩展由 ROKAE 提供，分发条件以厂商许可为准，
本说明不授予额外的再分发权利。现场标定、模型、图像和数据集需分别确认权属。
