"""Production identifier adapter shared by HTTP and administrative composition roots."""

from collections.abc import Callable
from uuid import UUID, uuid4


class RandomIdGenerator:
    def __init__(self, generate: Callable[[], UUID] = uuid4):
        self._generate = generate

    def new_id(self) -> UUID:
        return self._generate()
