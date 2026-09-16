from pydantic_settings import BaseSettings
from typing import List, Optional
from pydantic import Field, field_validator

class Settings(BaseSettings):
    database_url: str
    secret_key: str
    tolerance: float = 0.001
    issue_buffer_percent: float = 1.05
    default_sizes: str = "26,28,30,32,34,36,38,40,42,44,46,48,50,52,54"
    company_name: str = "Sneha Creations"
    company_address: str = "Head Off: No. 5 & 12 Ground Floor Chunchagatta Main Yelachanahalli, Bangalore - 560 062"
    company_gst: str = "29ABUFS5873N1ZU"
    company_state: str = "Karnataka"
    workflow: str = "BUYER_ORDER,BOM,MATERIAL_REQUIREMENT,RM_ORDER,GRN,ISSUE_RM,LIFECYCLE"

    @field_validator('default_sizes', mode='before')
    @classmethod
    def parse_default_sizes(cls, v):
        if isinstance(v, str):
            return v
        return v

    @field_validator('workflow', mode='before')
    @classmethod
    def parse_workflow(cls, v):
        if isinstance(v, str):
            return v
        return v

    def get_default_sizes_list(self) -> List[int]:
        return [int(x.strip()) for x in self.default_sizes.split(',') if x.strip()]

    def get_workflow_list(self) -> List[str]:
        return [x.strip() for x in self.workflow.split(',') if x.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
