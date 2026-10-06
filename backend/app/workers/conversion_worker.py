import logging

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    logger.info(
        "Conversion worker scaffold is installed; durable queue processing is not implemented."
    )


if __name__ == "__main__":
    main()

