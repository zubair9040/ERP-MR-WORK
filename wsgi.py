from erp import create_app

app = create_app()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("ERP_HOST", "0.0.0.0")
    dev = os.environ.get("ERP_DEBUG") == "1"
    print(f"ERP running at http://localhost:{port}")
    if dev:
        # auto-reload: code and template changes show up on browser refresh
        app.config["TEMPLATES_AUTO_RELOAD"] = True
        app.jinja_env.auto_reload = True
    app.run(host=host, port=port, debug=False, use_reloader=dev)
