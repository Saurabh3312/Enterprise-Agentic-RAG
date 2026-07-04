"""
Desktop launcher for the Enterprise Agentic RAG Platform.

This is what actually starts the app -- `Start Dashboard.bat` sets up the
Python environment once, then runs this every time. It:
  1. Starts Ollama in the background if it's installed but not running.
  2. Pulls the configured LLM model if it isn't downloaded yet.
  3. Starts the FastAPI/Uvicorn server.
  4. Opens the dashboard in your default browser once it's ready.

No `uvicorn ...` commands to remember -- just run this (or double-click
the .bat file, which does).
"""
import os
import time
import socket
import shutil
import threading
import webbrowser
import subprocess

APP_PORT = 8000
APP_URL = f"http://127.0.0.1:{APP_PORT}/app"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")


def port_in_use(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def ollama_available():
    return shutil.which("ollama") is not None


def start_ollama_serve():
    if not ollama_available():
        print("!  Ollama was not found on this computer.")
        print("   Download and install it from https://ollama.com/download")
        print("   then run:  ollama pull llama3.2:3b")
        print("   The dashboard will still open below, but the AI agent")
        print("   won't be able to answer questions until Ollama is set up.\n")
        return

    if port_in_use(11434):
        print("[OK] Ollama is already running.")
        return

    print("...  starting Ollama...")
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(20):
        if port_in_use(11434):
            print("[OK] Ollama is running.")
            return
        time.sleep(0.5)
    print("!  Ollama didn't start in time -- the agent may not respond yet.")


def ensure_ollama_model():
    if not ollama_available():
        return
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=15)
        if OLLAMA_MODEL not in result.stdout:
            print(f"...  downloading {OLLAMA_MODEL} (first run only, a few GB, needs internet)...")
            subprocess.run(["ollama", "pull", OLLAMA_MODEL], check=False)
        else:
            print(f"[OK] Model {OLLAMA_MODEL} is ready.")
    except Exception as e:
        print(f"!  Could not check Ollama models: {e}")


def open_browser_when_ready():
    for _ in range(120):
        if port_in_use(APP_PORT):
            webbrowser.open(APP_URL)
            return
        time.sleep(0.5)
    print(f"!  Server took a while to start -- open {APP_URL} manually if it didn't appear.")


def main():
    print("=" * 60)
    print("  Enterprise Agentic RAG Platform")
    print("=" * 60)
    print()

    start_ollama_serve()
    ensure_ollama_model()

    threading.Thread(target=open_browser_when_ready, daemon=True).start()

    print(f"\n[OK] Starting dashboard at {APP_URL}")
    print("     Keep this window open while using the dashboard.")
    print("     Close this window (or press Ctrl+C) to stop it.\n")

    import uvicorn
    from app.main import app as fastapi_app
    uvicorn.run(fastapi_app, host="127.0.0.1", port=APP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
