"""Static container safety checks that do not require Docker on Windows."""

from pathlib import Path


def test_product_core_image_is_nonroot_without_ssh_and_uses_candidate_entrypoint() -> None:
    dockerfile = Path("infra/product-core/Dockerfile").read_text(encoding="utf-8")

    assert "USER 10001:10001" in dockerfile
    assert "EXPOSE 8080" in dockerfile
    assert "akc_product_core.__main__:app" in dockerfile
    assert "TAVONEL_CORE_ALLOW_CUSTOMER_DATA=true" not in dockerfile
    assert "openssh" not in dockerfile.casefold()
    assert " 22" not in dockerfile


def test_product_core_build_publishes_the_declared_image() -> None:
    build = Path("infra/product-core/cloudbuild.yaml").read_text(encoding="utf-8")

    assert "infra/product-core/Dockerfile" in build
    assert "images:\n  - ${_IMAGE}" in build
    assert "logging: CLOUD_LOGGING_ONLY" in build
