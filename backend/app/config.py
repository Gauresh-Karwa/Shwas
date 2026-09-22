import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    CPCB_API_KEY: str = os.getenv("CPCB_API_KEY","")
    CPCB_RESOURCE_ID: str = os.getenv("CPCB_RESOURCE_ID","3b01bcb8-0b14-4abf-b6f2-c1bfd384ba69")
    CPCB_BASE_URL: str = "https://api.data.gov.in/resource"
    OPENWEATHERMAP_API_KEY: str = os.getenv("OPENWEATHERMAP_API_KEY","")

    FIRMS_MAP_KEY: str = os.getenv("FIRMS_MAP_KEY", "")

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://shwas_user:shwas_password@localhost:5432/shwas_db"
    )

    TARGET_CITY: str = os.getenv("TARGET_CITY","Mumbai")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    def validate(self) -> list[str]:
        missing = []
        if not self.CPCB_API_KEY:
            missing.append("CPCB_API_KEY")
        return missing

settings = Settings()
