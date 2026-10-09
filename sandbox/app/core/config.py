from typing import List, Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ORIGINS: List[str] = ["*"]
    
    # Service timeout settings (minutes)
    SERVICE_TIMEOUT_MINUTES: Optional[int] = None
    
    # Log configuration
    LOG_LEVEL: str = "INFO"

    # CLI engine (agy/claude) process management — docs/spec/01-dong-co-cli.md,
    # docs/design/dot-2-cli-engine.md muc 1.3. Chi so sanh os.path.basename(argv[0]).
    ENGINE_ALLOWED_BINARIES: str = "agy,claude"
    # StreamReader mac dinh chi 64 KiB — dong NDJSON co tool_info.output vuot
    # ngay; phai truyen limit lon hon khi tao subprocess.
    ENGINE_MAX_LINE_BYTES: int = 8 * 1024 * 1024
    # Vong dem phat lai (deque) moi engine_id, dung cho ?from_seq=N noi lai
    # sau khi phien di qua WAITING.
    ENGINE_BUFFER_LINES: int = 20000
    # Giu registry (de /engine/status, /engine/events con doc duoc) bao nhieu
    # giay sau khi tien trinh da chet truoc khi xoa han.
    ENGINE_KEEP_AFTER_EXIT_SECONDS: int = 300

    @field_validator("ORIGINS", mode="before")
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> Union[List[str], str]:
        if isinstance(v, str) and not v.startswith("["):
            return [i.strip() for i in v.split(",")]
        elif isinstance(v, (list, str)):
            return v
        raise ValueError(v)

    class Config:
        case_sensitive = True
        env_file = ".env"


settings = Settings() 