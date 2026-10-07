"""Create an isolated reset demo DB for browser tests; never touch the default DB."""
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ["DEMO_MODE"]="true"
DB=ROOT/".demo"/"block4-playwright.db"
os.environ["DATABASE_URL"]=f"sqlite:///{DB.as_posix()}"
from scripts.reset_demo import reset_demo
from scripts.seed_accounts import write_credentials
write_credentials(reset_demo(os.environ["DATABASE_URL"], passwords={
    "official":"offline-judge-password", "operator":"offline-judge-password",
    "buyer":"offline-judge-password", "farmer":"offline-judge-password"}))
