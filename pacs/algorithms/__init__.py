"""알고리즘 모듈 목록. 화면은 여기서 쓸 수 있는 알고리즘을 가져온다.

알고리즘 담당자가 pacs/algorithms/<이름>.py를 만들면 자동으로 목록에 들어온다.
각 모듈은 apply(image, **params) -> image 와 PARAMS를 가진다 (README "서로 맞춰야 하는 부분").
아직 만들지 않은 알고리즘은 목록에서 빠질 뿐 오류를 내지 않는다.
"""
import importlib

from pacs import config


def available():
    """{이름: 모듈}. config.ALGORITHMS 순서를 따른다."""
    found = {}
    for name in config.ALGORITHMS:
        module_name = f"{__name__}.{name}"
        try:
            found[name] = importlib.import_module(module_name)
        except ModuleNotFoundError as e:
            if e.name != module_name:  # 모듈은 있는데 그 안에서 다른 import가 실패한 경우는 숨기지 않는다
                raise
    return found
