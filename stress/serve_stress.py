"""Serve the seeded stress database for a load test.

    python stress/serve_stress.py            # port 5000

Uses `waitress <https://pypi.org/project/waitress/>`_ when it is installed --
a real multi-threaded WSGI server, which is what you want under load.  Falls
back to Flask's development server (threaded, no reloader, no debugger) so the
procedure works out of the box, at a lower ceiling.

Never point a load test at ``flask run --debug``: the debugger and reloader
serialise requests and you end up measuring them instead of the application.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from seed_stress import CONFIG, build_app  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--threads", type=int, default=16,
                        help="waitress worker threads (default 16)")
    arguments = parser.parse_args()

    if not os.path.exists(CONFIG["DATABASE"]):
        sys.exit(f"No stress database at {CONFIG['DATABASE']}.\n"
                 f"Run:  python stress/seed_stress.py --users 1000 --fresh")

    application = build_app()

    try:
        from waitress import serve
    except ImportError:
        print("waitress is not installed -- falling back to the Flask "
              "development server.\n  pip install waitress   (recommended for "
              "runs above a few hundred users)")
        application.run(host=arguments.host, port=arguments.port,
                        threaded=True, debug=False, use_reloader=False)
    else:
        print(f"waitress serving on http://{arguments.host}:{arguments.port}"
              f" with {arguments.threads} threads")
        serve(application, host=arguments.host, port=arguments.port,
              threads=arguments.threads)
