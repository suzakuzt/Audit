from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POPPLER_BIN = Path(r"C:\Program Files\poppler\poppler-24.08.0\Library\bin")


class Settings(BaseSettings):
    app_name: str = Field(default="Audit System", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    database_url: str = Field(default="sqlite:///./audit_system.db", alias="APP_DATABASE_URL")
    llm_api_key: str = Field(default="", alias="AUDIT_LLM_API_KEY")
    llm_model: str = Field(default="deepseek-chat", alias="AUDIT_LLM_MODEL")
    llm_base_url: str | None = Field(default="https://api.deepseek.com", alias="AUDIT_LLM_BASE_URL")
    llm_timeout: int = Field(default=180, alias="AUDIT_LLM_TIMEOUT")
    ocr_model: str | None = Field(default="deepseek-chat", alias="AUDIT_OCR_MODEL")
    ocr_max_pages: int = Field(default=3, alias="AUDIT_OCR_MAX_PAGES")
    ocr_engine_preference: str = Field(default="paddle_only", alias="AUDIT_OCR_ENGINE_PREFERENCE")
    paddle_ocr_api_url: str = Field(default="", alias="AUDIT_PADDLE_OCR_API_URL")
    paddle_ocr_api_token: str = Field(default="", alias="AUDIT_PADDLE_OCR_API_TOKEN")
    paddle_ocr_api_timeout: int = Field(default=180, alias="AUDIT_PADDLE_OCR_API_TIMEOUT")
    paddle_ocr_python_path: Path = Field(
        default=Path(".venv_paddleocr/Scripts/python.exe"),
        alias="AUDIT_PADDLE_OCR_PYTHON_PATH",
    )
    pdfinfo_path: Path = Field(
        default=Path(r"C:\Program Files\poppler\poppler-24.08.0\Library\bin\pdfinfo.exe"),
        alias="AUDIT_PDFINFO_PATH",
    )
    pdftotext_path: Path = Field(
        default=Path(r"C:\Program Files\poppler\poppler-24.08.0\Library\bin\pdftotext.exe"),
        alias="AUDIT_PDFTOTEXT_PATH",
    )
    pdftoppm_path: Path = Field(
        default=Path(r"C:\Program Files\poppler\poppler-24.08.0\Library\bin\pdftoppm.exe"),
        alias="AUDIT_PDFTOPPM_PATH",
    )
    runtime_temp_dir: Path = Field(default=Path(".runtime_tmp"), alias="AUDIT_RUNTIME_TEMP_DIR")
    validation_max_parallel: int = Field(default=2, alias="AUDIT_VALIDATION_MAX_PARALLEL")
    validation_include_visual_assets: bool = Field(default=True, alias="AUDIT_VALIDATION_INCLUDE_VISUAL_ASSETS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    def model_post_init(self, __context: object) -> None:
        self.runtime_temp_dir = self._resolve_project_path(self.runtime_temp_dir)
        self.paddle_ocr_python_path = self._resolve_project_path(self.paddle_ocr_python_path)
        self.pdfinfo_path = self._resolve_tool_path(self.pdfinfo_path, "pdfinfo.exe")
        self.pdftotext_path = self._resolve_tool_path(self.pdftotext_path, "pdftotext.exe")
        self.pdftoppm_path = self._resolve_tool_path(self.pdftoppm_path, "pdftoppm.exe")

    @staticmethod
    def _resolve_project_path(path: Path) -> Path:
        return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()

    @staticmethod
    def _resolve_tool_path(path: Path, executable_name: str) -> Path:
        if path.exists():
            return path
        candidate = DEFAULT_POPPLER_BIN / executable_name
        if candidate.exists():
            return candidate
        return path


settings = Settings()
