"""
Unit and integration tests for Part 28: Mobile-Friendly Web Portals.
Verifies viewport meta tags, responsive CSS media queries, table overflow containers,
touch target sizing (>= 44px), and 360px viewport compatibility.
"""
import os
import sys
import pytest

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import create_app
from db import db

DASHBOARD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "dashboard"))
TEMPLATES_DIR = os.path.join(DASHBOARD_DIR, "templates")
CSS_DIR = os.path.join(DASHBOARD_DIR, "static", "css")

@pytest.fixture
def client():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["TELEGRAM_POLLING_ENABLED"] = "False"
    from config import Config
    Config.TESTING = True
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()

def test_viewport_meta_tag_in_all_templates():
    """Verify viewport meta tag exists in base.html and all standalone templates."""
    base_path = os.path.join(TEMPLATES_DIR, "base.html")
    with open(base_path, "r", encoding="utf-8") as f:
        base_content = f.read()
    assert 'name="viewport"' in base_content, "base.html must declare viewport meta tag"
    assert "width=device-width" in base_content, "base.html viewport must include width=device-width"

    # All standalone templates that do not extend base.html must declare viewport
    standalone_templates = ["user_dashboard.html", "user_login.html", "user_register.html"]
    for tmpl in standalone_templates:
        tmpl_path = os.path.join(TEMPLATES_DIR, tmpl)
        with open(tmpl_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert 'name="viewport"' in content, f"{tmpl} must declare viewport meta tag"
        assert "width=device-width" in content, f"{tmpl} viewport must set width=device-width"

def test_all_tables_wrapped_in_table_wrapper():
    """Verify that every <table> element in templates is contained inside a .table-wrapper."""
    for root, _, files in os.walk(TEMPLATES_DIR):
        for file in files:
            if file.endswith(".html"):
                path = os.path.join(root, file)
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # If template contains <table, check that it also contains table-wrapper
                if "<table" in content:
                    assert "table-wrapper" in content, f"Template {file} contains <table> but lacks .table-wrapper container"

def test_responsive_css_media_queries_exist():
    """Verify responsive media queries for 768px and 360px viewports exist in both stylesheets."""
    main_css_path = os.path.join(CSS_DIR, "main.css")
    user_css_path = os.path.join(CSS_DIR, "user.css")

    with open(main_css_path, "r", encoding="utf-8") as f:
        main_css = f.read()
    with open(user_css_path, "r", encoding="utf-8") as f:
        user_css = f.read()

    # main.css checks
    assert "@media (max-width: 768px)" in main_css, "main.css must contain 768px media query"
    assert "@media (max-width: 360px)" in main_css, "main.css must contain 360px mobile media query"

    # user.css checks
    assert "@media (max-width: 768px)" in user_css, "user.css must contain 768px media query"
    assert "@media (max-width: 360px)" in user_css, "user.css must contain 360px mobile media query"

def test_touch_target_minimum_dimensions():
    """Verify that interactive elements meet the minimum 44px touch target guidelines."""
    main_css_path = os.path.join(CSS_DIR, "main.css")
    user_css_path = os.path.join(CSS_DIR, "user.css")

    with open(main_css_path, "r", encoding="utf-8") as f:
        main_css = f.read()
    with open(user_css_path, "r", encoding="utf-8") as f:
        user_css = f.read()

    # Verify min-height of 44px on buttons and inputs
    assert "min-height: 44px" in main_css, "main.css must specify min-height: 44px for touch targets"
    assert "min-width: 44px" in main_css, "main.css must specify min-width: 44px for touch targets"

    assert "min-height: 44px" in user_css, "user.css must specify min-height: 44px for touch targets"
    assert "min-width: 44px" in user_css, "user.css must specify min-width: 44px for touch targets"

def test_table_overflow_x_rule():
    """Verify .table-wrapper has overflow-x: auto configured in CSS."""
    main_css_path = os.path.join(CSS_DIR, "main.css")
    user_css_path = os.path.join(CSS_DIR, "user.css")

    with open(main_css_path, "r", encoding="utf-8") as f:
        main_css = f.read()
    with open(user_css_path, "r", encoding="utf-8") as f:
        user_css = f.read()

    assert ".table-wrapper" in main_css and "overflow-x: auto" in main_css
    assert ".table-wrapper" in user_css and "overflow-x: auto" in user_css

def test_endpoints_render_with_viewport_and_no_overflow(client):
    """Verify rendered HTML responses from Flask contain viewport meta and valid markup."""
    endpoints = [
        "/",
        "/user/login",
        "/user/register",
        "/admin/overview",
        "/admin/alerts",
        "/admin/transactions",
        "/admin/users",
        "/admin/models",
        "/admin/drift"
    ]
    for ep in endpoints:
        resp = client.get(ep)
        assert resp.status_code == 200, f"Endpoint {ep} failed with status {resp.status_code}"
        html = resp.get_data(as_text=True)
        assert 'name="viewport"' in html, f"Rendered HTML for {ep} missing viewport meta tag"
        assert "width=device-width" in html, f"Rendered HTML for {ep} missing width=device-width"
