from erp import create_app

app = create_app()

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    print(f"ERP running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("ERP_DEBUG") == "1")
