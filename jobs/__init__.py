"""Cron-executable research jobs.

Every job is a module with a ``main()`` and an ``if __name__ == "__main__"``
guard, so it runs as ``python -m jobs.<name>`` with no browser session and no
web server involved (spec s6).
"""
