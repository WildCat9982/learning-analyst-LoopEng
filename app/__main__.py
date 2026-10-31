import argparse

from . import create_app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=4000)
    args = parser.parse_args()
    create_app().run(host=args.host, port=args.port, threaded=False)
