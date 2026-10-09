from enum import Enum

from pydantic import BaseModel, Field


class HostInfo(BaseModel):
    hostname: str = ""
    os_release: str = ""
    kernel: str = ""
    uptime_s: float = 0.0


class CpuInfo(BaseModel):
    cores: int = 0
    utilization_total: float = 0.0
    utilization_per_core: list[float] = Field(default_factory=list)
    load1: float = 0.0
    load5: float = 0.0
    load15: float = 0.0


class MemInfo(BaseModel):
    total: int = 0
    used: int = 0
    available: int = 0
    cached: int = 0
    swap_total: int = 0
    swap_used: int = 0


class DiskInfo(BaseModel):
    mount: str = ""
    total: int = 0
    used: int = 0
    avail: int = 0
    pct: float = 0.0


class GpuInfo(BaseModel):
    index: int = 0
    name: str = ""
    uuid: str = ""
    utilization: float | None = None
    mem_utilization: float | None = None
    mem_used: float | None = None
    mem_total: float | None = None
    temperature: float | None = None
    power_draw: float | None = None
    power_limit: float | None = None
    fan_speed: float | None = None


class GpuProcess(BaseModel):
    pid: int = 0
    user: str = ""
    command: str = ""
    gpu_mem_mb: float | None = None
    gpu_index: int | None = None
    elapsed: str = ""


class NetIface(BaseModel):
    name: str = ""
    rx_bytes: int = 0
    tx_bytes: int = 0


class TopProcess(BaseModel):
    pid: int = 0
    user: str = ""
    cpu: float = 0.0
    mem: float = 0.0
    command: str = ""


class Snapshot(BaseModel):
    ts: float
    errors: list[str] = Field(default_factory=list)
    host: HostInfo = Field(default_factory=HostInfo)
    cpu: CpuInfo = Field(default_factory=CpuInfo)
    memory: MemInfo = Field(default_factory=MemInfo)
    disks: list[DiskInfo] = Field(default_factory=list)
    gpus: list[GpuInfo] = Field(default_factory=list)
    gpu_processes: list[GpuProcess] = Field(default_factory=list)
    net: list[NetIface] = Field(default_factory=list)
    top_cpu: list[TopProcess] = Field(default_factory=list)
    top_mem: list[TopProcess] = Field(default_factory=list)


class ServerStatus(str, Enum):
    online = "online"
    offline = "offline"
    degraded = "degraded"


class ServerState(BaseModel):
    id: str
    name: str
    status: ServerStatus = ServerStatus.offline
    last_error: str | None = None
    last_success_ts: float | None = None
    snapshot: Snapshot | None = None
