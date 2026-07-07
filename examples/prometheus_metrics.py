from __future__ import annotations

from backstop import Backstop


def main() -> None:
    Backstop.start_metrics_server(port=9090)
    print("Backstop metrics listening on http://localhost:9090/metrics")
    input("Press Enter to stop.\n")


if __name__ == "__main__":
    main()
