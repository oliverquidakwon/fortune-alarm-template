# -*- coding: utf-8 -*-
"""공용 준비물 — 예시 인물 하늘·바다의 명식(chart). 인물 설명은 examples.py."""
import pytest

import chart_factory
from examples import bada_birth, haneul_birth


@pytest.fixture(scope="session")
def haneul():
    return chart_factory.build(haneul_birth())


@pytest.fixture(scope="session")
def bada_a():
    return chart_factory.build(bada_birth("A"))


@pytest.fixture(scope="session")
def bada_b():
    return chart_factory.build(bada_birth("B"))
