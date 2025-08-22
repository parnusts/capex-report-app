import os, socket, time, requests
from flask import Flask, request, jsonify

APP_TOKEN = os.getenv("PROBE_TOKEN", "changeme")

MYSQL_HOST = os.getenv("MYSQL_HOST", "103.28.240.24")  # adjust if needed
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MSSQL_HOST = os.getenv("MSSQL_HOST", "10.1.1.100")     # private → will fail from cloud
MSSQL_PORT = int(os.getenv("MSSQL_PORT", "1433"))

app = Flask(__name__)

def tcp_ping(host, port, timeout=3):
    t0 = time.time()
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, port))
        return True, f"{round((time.time()-t0)*1000)} ms"
    except Exception as e:
        return False, str(e)
    finally:
        try: s.close()
        except: pass

@app.get("/debug/egress-ip")
def egress_ip():
    if request.args.get("token") != APP_TOKEN:
        return ("forbidden", 403)
    try:
        ip = requests.get("https://api.ipify.org", timeout=4).text.strip()
        return jsonify(ip=ip)
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.get("/debug/netcheck")
def netcheck():
    if request.args.get("token") != APP_TOKEN:
        return ("forbidden", 403)
    results = {}
    for name, host, port in [("mysql", MYSQL_HOST, MYSQL_PORT),
                             ("mssql", MSSQL_HOST, MSSQL_PORT)]:
        ok, info = tcp_ping(host, port)
        results[name] = {"ok": ok, "info": info, "host": host, "port": port}
    return jsonify(results)

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
