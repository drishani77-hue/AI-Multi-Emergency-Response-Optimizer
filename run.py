"""Run the ResQTech Flask API and its allocation background worker."""

import logging

from backend.app import create_app, get_allocation_coordinator, get_road_engine
from backend.allocation_worker import AllocationWorker


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    app = create_app()
    coordinator = get_allocation_coordinator(app)
    road_engine = get_road_engine(app)
    worker = AllocationWorker(coordinator)

    worker.start()

    try:
        app.run(
            host="127.0.0.1",
            port=5000,
            debug=False,
            use_reloader=False,
        )
    finally:
        if worker.stop(timeout=30):
            coordinator.close()
            road_engine.close()
        else:
            logging.getLogger(__name__).error(
                "Allocation worker did not stop; native resources were left open."
            )


if __name__ == "__main__":
    main()
