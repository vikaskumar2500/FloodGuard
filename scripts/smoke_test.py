"""Read-only HTTP smoke checks for an already-running Phase 1 stack."""

import argparse
import json
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--frontend-url", default="http://localhost:3000")
    parser.add_argument("--api-prefix", default="/api/v1")
    parser.add_argument("--origin", help="Configured browser origin, if different from fetch URL")
    args = parser.parse_args()
    api = args.api_url.rstrip("/")
    frontend = args.frontend_url.rstrip("/")
    origin = args.origin or frontend
    for path in ("/health", "/health/live", f"{args.api_prefix}/health/live"):
        with urlopen(api + path, timeout=10) as response:
            assert response.status == 200
            assert json.load(response)["status"] == "healthy"
        print(f"PASS {path}")
    for path in (f"{args.api_prefix}/health", f"{args.api_prefix}/health/ready"):
        request = Request(api + path, headers={"Origin": origin})
        with urlopen(request, timeout=10) as response:
            body = json.load(response)
            assert response.status == 200 and body["ready"] is True
            assert all(value["status"] == "healthy" for value in body["dependencies"].values())
            assert response.headers["Access-Control-Allow-Origin"] == origin
        print(f"PASS {path}: PostgreSQL, PostGIS, Redis and configured CORS")
    with urlopen(api + "/docs", timeout=10) as response:
        assert response.status == 200 and "swagger" in response.read().decode().lower()
    print("PASS Swagger UI")
    with urlopen(frontend + "/", timeout=60) as response:
        html = response.read().decode()
        assert response.status == 200 and "FloodGuard" in html and "System status" in html
    print("PASS Next.js page")
    with urlopen(frontend + "/health", timeout=10) as response:
        assert json.load(response)["status"] == "healthy"
    print("PASS Next.js liveness")


if __name__ == "__main__":
    main()
