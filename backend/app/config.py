from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load the project-root .env BEFORE Settings() runs.
_ROOT_ENV = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_ROOT_ENV)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ROOT_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    jwt_secret: str = ""  # presence enforced by auth.py, not here

    tolerance: float = 0.001
    issue_buffer_percent: float = 1.05
    default_sizes: str = "26,28,30,32,34,36,38,40,42,44,46,48,50,52,54"
    company_name: str = "Sneha Creations"
    company_address: str = "Head Off: No. 5 & 12 Ground Floor Chunchagatta Main Yelachanahalli, Bangalore - 560 062"
    company_gst: str = "29ABUFS5873N1ZU"
    company_state: str = "Karnataka"
    workflow: str = "BUYER_ORDER,BOM,MATERIAL_REQUIREMENT,RM_ORDER,GRN,ISSUE_RM,LIFECYCLE"

    def get_default_sizes_list(self) -> List[int]:
        return [int(x.strip()) for x in self.default_sizes.split(",") if x.strip()]

    def get_workflow_list(self) -> List[str]:
        return [x.strip() for x in self.workflow.split(",") if x.strip()]


settings = Settings()
