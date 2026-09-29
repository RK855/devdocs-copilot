"""
应用配置模块
双供应商架构：
  - Agnes（agnes-2.5-flash）：聊天模型
  - 硅基流动（BAAI/bge-m3）：Embedding
配置从项目根目录的 .env 读取，自动支持同名环境变量覆盖。
"""
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（本文件位于 app/config.py，上两级即根目录）
# 所有相对路径都以它为锚点，换工作目录启动也不会漂移
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    应用配置类
    属性名即环境变量名（不区分大小写），pydantic-settings 自动读取并校验类型
    """

    # ===== 聊天模型：Agnes（OpenAI 兼容） =====
    AGNES_API_KEY: str = ""
    AGNES_BASE_URL: str = "https://apihub.agnes-ai.com/v1"
    CHAT_MODEL: str = "agnes-2.5-flash"
    LLM_TIMEOUT: float = 30.0                # 单次请求超时（秒）
    LLM_TEMPERATURE: float = 0.3             # RAG 求稳，低发散
    LLM_MAX_TOKENS: int = 1024               # 含 reasoning_content 余量

    # ===== Embedding：硅基流动（OpenAI 兼容） =====
    SILICONFLOW_API_KEY: str = ""
    SILICONFLOW_BASE_URL: str = "https://api.siliconflow.cn/v1"
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIM: int = 1024                 # bge-m3 向量维度，建库后不可变
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANK_ENABLED: bool = True               # F7：RRF 后接 bge-reranker 精排；False 退回 F6 纯 RRF
    RERANK_TIMEOUT: float = 20.0              # rerank 单次请求超时（秒）
    # F7 二次证据门：rerank 真实打分 top1 低于此值视为"粗排误放行"，改判拒答。
    # 阈值取自 30 题评测实测间隔（无答案题 ≤0.003，最弱可答题 0.077）；
    # fail-open 降级（scored=False）时此门不生效，供应商故障不造成误拒。
    RERANK_THRESHOLD: float = 0.02

    # ===== 服务配置 =====
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True                        # True 时开启热重载

    # ===== Agent（F8） =====
    AGENT_MAX_STEPS: int = 5                  # ReAct 最大 LLM 轮数（工具调用轮数上限）

    # ===== 向量数据库 =====
    COLLECTION_NAME: str = "devdocs"
    CHROMA_DATA_DIR: Path = BASE_DIR / "data" / "chroma"

    # ===== 文档配置 =====
    CHUNK_SIZE: int = 500                     # 每个文本块大小（字符数）
    CHUNK_OVERLAP: int = 50                   # 块间重叠（字符数）
    UPLOAD_DIR: Path = BASE_DIR / "uploads"

    # ===== 检索配置（两阶段：粗排 → RRF → 精排） =====
    RETRIEVAL_MODE: str = "hybrid"            # 问答默认检索模式：vector / bm25 / hybrid（F6）
    CANDIDATE_K: int = 20                     # 单路检索候选数（向量/BM25 各取）
    FUSED_K: int = 10                         # RRF 融合后数量
    TOP_K: int = 5                            # Rerank 后最终返回数量
    RELEVANCE_THRESHOLD: float = 0.45         # 最高相似度低于此值视为无相关内容，直接拒答
                                             # 依据真实观测校准：相关问题 0.76 / 无关问题 0.35

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",           # .env 固定从项目根读取
        env_file_encoding="utf-8",
        extra="ignore",                       # .env 里多余的键不报错
    )

    @model_validator(mode="after")
    def anchor_relative_paths(self) -> "Settings":
        """.env 里若写了相对路径，统一锚定到项目根目录，避免依赖启动时的工作目录"""
        for name in ("CHROMA_DATA_DIR", "UPLOAD_DIR"):
            path = getattr(self, name)
            if not path.is_absolute():
                setattr(self, name, (BASE_DIR / path).resolve())
        return self


# 全局单例，整个项目统一从这里取配置
settings = Settings()
