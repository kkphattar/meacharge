# run.py
import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    debug = os.getenv('FLASK_DEBUG', '0') == '1'

    if os.getenv('DEBUGPY_ENABLE', '0') == '1':
        import debugpy
        debugpy.listen(("0.0.0.0", 5678))
        print("VS Code debugger waiting on port 5678...")
        debugpy.wait_for_client()

    app.run(host="0.0.0.0", port=5000, debug=debug, use_reloader=False)