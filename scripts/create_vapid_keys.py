"""Create local VAPID configuration without printing keys or enabling delivery."""

import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    destination = root / "outputs" / "local-vapid.env"
    destination.parent.mkdir(exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode().rstrip("=")

    # Exclusive creation: never replace an existing notification identity.
    with destination.open("x", encoding="utf-8") as stream:
        stream.write(
            f"ENABLE_WEB_PUSH=false\nVAPID_PUBLIC_KEY={encode(public)}\nVAPID_PRIVATE_KEY={encode(private)}\nVAPID_SUBJECT=\n"
        )
    print(
        "Created outputs/local-vapid.env (Git-ignored). Configure a contact subject; keep the private key server-only."
    )


if __name__ == "__main__":
    main()
