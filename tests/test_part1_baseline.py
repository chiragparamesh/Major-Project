import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def test_env_example_exists_and_contains_standard_keys():
    root_env_example = PROJECT_ROOT / ".env.example"
    backend_env_example = PROJECT_ROOT / "backend" / ".env.example"
    
    assert root_env_example.exists(), "Root .env.example must exist"
    assert backend_env_example.exists(), "Backend .env.example must exist"
    
    content = root_env_example.read_text(encoding="utf-8")
    assert "MLBFD_SECRET_KEY" in content
    assert "JWT_SECRET_KEY" in content
    assert "VIRTUAL_BALANCE" in content
    assert "DATABASE_URL" in content

def test_backend_config_importable():
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "backend"))
    from config import Config
    assert hasattr(Config, "SECRET_KEY")
    assert hasattr(Config, "JWT_SECRET_KEY")
    assert hasattr(Config, "VIRTUAL_BALANCE")

def test_no_legacy_brand_in_ui_templates():
    legacy_brand = "".join(["B", "e", "y", "o", "n", "d", "O", "T", "P"])
    templates_dir = PROJECT_ROOT / "dashboard" / "templates"
    for html_file in templates_dir.glob("*.html"):
        content = html_file.read_text(encoding="utf-8")
        assert legacy_brand.lower() not in content.lower(), f"Legacy brand reference found in {html_file.name}"
    
    # Check that parent and standalone portal templates define the MLBFD brand
    for main_template in ["base.html", "user_dashboard.html", "user_login.html", "user_register.html"]:
        content = (templates_dir / main_template).read_text(encoding="utf-8")
        assert "MLBFD" in content, f"MLBFD brand missing from {main_template}"
